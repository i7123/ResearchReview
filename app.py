import os
import re
import uuid
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import pypdf
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import database
import agents

app = FastAPI(title="ResearchReview API")

# Ensure required directories exist
os.makedirs("data/pdfs", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)

# Initialize database
database.init_db()

# Models
class FeedbackRequest(BaseModel):
    feedback: str
    model: str = agents.DEFAULT_MODEL

class CategoryCreate(BaseModel):
    name: str
    description: str = ""

class ArxivRequest(BaseModel):
    url_or_id: str
    model: str = agents.DEFAULT_MODEL

# Helpers
def extract_pdf_text(file_path: str) -> str:
    """Extracts raw text from a PDF file using pypdf."""
    reader = pypdf.PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text

def parse_arxiv_id(url_or_id: str) -> str:
    """Extracts arXiv ID from a URL or raw ID string."""
    url_or_id = url_or_id.strip()
    # Match pattern like: https://arxiv.org/abs/1706.03762 or 1706.03762
    match = re.search(r'(?:arxiv\.org/(?:abs|pdf)/|arxiv:)?([0-9]+\.[0-9]+v?[0-9]*)', url_or_id, re.IGNORECASE)
    if match:
        return match.group(1)
    # Check for older formats (e.g. hep-th/9711200)
    match_old = re.search(r'([a-z\-]+/[0-9]+)', url_or_id, re.IGNORECASE)
    if match_old:
        return match_old.group(1)
    return url_or_id

def fetch_arxiv_metadata_and_pdf(arxiv_id: str) -> tuple:
    """Queries arXiv API for metadata and downloads the PDF."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    # Query API
    api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect to arXiv API: {str(e)}")
        
    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="arXiv API rate limit exceeded. Please try again later, or download the PDF and upload it directly."
        )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"arXiv API returned status code {response.status_code}")
    
    # Parse XML
    try:
        root = ET.fromstring(response.content)
        # XML Namespaces
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entry = root.find('atom:entry', ns)
        if entry is None or entry.find('atom:title', ns) is None:
            raise HTTPException(status_code=404, detail="Paper not found on arXiv")
        
        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        abstract = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
        
        authors_list = []
        for author in entry.findall('atom:author', ns):
            name = author.find('atom:name', ns).text.strip()
            authors_list.append(name)
        authors = ", ".join(authors_list)
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error parsing arXiv metadata: {str(e)}")
    
    # Download PDF
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_path = f"data/pdfs/arxiv_{arxiv_id}.pdf"
    
    try:
        pdf_response = requests.get(pdf_url, headers=headers, timeout=15)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect to download arXiv PDF: {str(e)}")
        
    if pdf_response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="arXiv PDF download rate limit exceeded. Please download the PDF manually and upload it directly."
        )
    if pdf_response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"arXiv PDF download returned status code {pdf_response.status_code}")
    
    with open(pdf_path, 'wb') as f:
        f.write(pdf_response.content)
        
    return title, authors, abstract, pdf_path

def append_to_log(paper_id: str, message: str):
    """Appends an execution log message to a file for this paper."""
    log_path = f"data/logs/{paper_id}.log"
    with open(log_path, "a") as f:
        f.write(message + "\n")

# Background Pipeline Execution
def run_pipeline_task(paper_id: str, text: str, arxiv_id: str = None, file_path: str = None, model: str = agents.DEFAULT_MODEL):
    database.update_review_status(paper_id, 'processing')
    append_to_log(paper_id, f"Initializing background agents with model {model}...")
    
    def log_callback(msg):
        append_to_log(paper_id, msg)
        
    try:
        # Run orchestrator synchronously in the background thread
        import asyncio
        asyncio.run(agents.run_full_pipeline(
            paper_id=paper_id,
            raw_text=text,
            arxiv_id=arxiv_id,
            file_path=file_path,
            model=model,
            on_log_callback=log_callback
        ))
    except Exception as e:
        append_to_log(paper_id, f"Pipeline execution failed: {str(e)}")

# Background Reflection Task
def run_reflection_task(paper_id: str, paper_data: dict, current_review: dict, feedback: str, logs: list, model: str):
    append_to_log(paper_id, f"Reflection Agent: Starting analysis of feedback with model {model}...")
    try:
        import asyncio
        # We need JSON representations for current_review
        import json
        
        # Load JSON representation of lists/objects in review
        review_dict = {
            "strengths": json.loads(current_review.get("strengths", "[]")),
            "weaknesses": json.loads(current_review.get("weaknesses", "[]")),
            "novelty": current_review.get("novelty", ""),
            "technical_correctness": current_review.get("technical_correctness", ""),
            "overall_score": current_review.get("overall_score", 3),
        }
        
        # Run reflection within async tracing wrapper
        reflection_agent = agents.ReflectionAgent(model)
        
        async def _run_reflection():
            async with agents.trace_agent_step(
                paper_id, 
                "Human Feedback Reflection Loop", 
                {"feedback": feedback, "history_length": len(logs)}
            ) as trace:
                res = await reflection_agent.reflect_and_update(
                    paper_details=paper_data,
                    current_review=review_dict,
                    user_feedback=feedback,
                    feedback_history=logs
                )
                trace["output"] = res
                return res
                
        update_result = asyncio.run(_run_reflection())
        
        # Save results
        database.save_review(
            paper_id=paper_id,
            strengths=json.dumps(update_result['review'].get('strengths', [])),
            weaknesses=json.dumps(update_result['review'].get('weaknesses', [])),
            novelty=update_result['review'].get('novelty', ''),
            technical_correctness=update_result['review'].get('technical_correctness', ''),
            overall_score=update_result['review'].get('overall_score', 3),
            feasibility_report=json.dumps(update_result['feasibility']),
            status='completed'
        )
        
        database.add_feedback_log(
            paper_id=paper_id,
            user_feedback=feedback,
            agent_reflection=update_result.get('reflection_summary', 'Incorporated user feedback.')
        )
        
        append_to_log(paper_id, "Reflection completed. Review and feasibility report successfully updated!")
    except Exception as e:
        append_to_log(paper_id, f"Reflection failed: {str(e)}")

# API Endpoints
@app.get("/api/categories")
def get_categories():
    return database.list_categories()

@app.post("/api/categories")
def create_category(cat: CategoryCreate):
    cat_id = database.add_category(cat.name, cat.description)
    if not cat_id:
         raise HTTPException(status_code=400, detail="Category already exists")
    return {"id": cat_id, "name": cat.name, "description": cat.description}

@app.get("/api/papers")
def get_papers():
    return database.list_papers()

@app.get("/api/papers/{paper_id}")
def get_paper_details(paper_id: str):
    paper = database.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
        
    review = database.get_review(paper_id)
    feedback_logs = database.get_feedback_logs(paper_id)
    
    return {
        "paper": paper,
        "review": review,
        "feedback_logs": feedback_logs
    }

@app.get("/api/papers/{paper_id}/logs")
def get_paper_logs(paper_id: str):
    log_path = f"data/logs/{paper_id}.log"
    if not os.path.exists(log_path):
        return {"logs": []}
    with open(log_path, "r") as f:
        logs = f.readlines()
    return {"logs": [line.strip() for line in logs]}

@app.get("/api/papers/{paper_id}/traces")
def get_paper_traces(paper_id: str):
    traces = database.get_agent_traces(paper_id)
    import json
    formatted_traces = []
    for t in traces:
        t_dict = dict(t)
        try:
            t_dict["input_data"] = json.loads(t_dict["input_data"])
        except Exception:
            pass
        try:
            t_dict["output_data"] = json.loads(t_dict["output_data"])
        except Exception:
            pass
        formatted_traces.append(t_dict)
    return formatted_traces

@app.post("/api/import/pdf")
def import_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...), model: str = Form(agents.DEFAULT_MODEL)):
    paper_id = uuid.uuid4().hex
    file_path = f"data/pdfs/{paper_id}_{file.filename}"
    
    # Save uploaded file
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(file.file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {str(e)}")
        
    # Extract text to ensure it's readable
    try:
        text = extract_pdf_text(file_path)
        if not text.strip():
            raise HTTPException(status_code=400, detail="Uploaded PDF is empty or unreadable (scanned images without OCR are not supported).")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read PDF: {str(e)}")
        
    # Add paper placeholder to database
    database.add_paper(
        paper_id=paper_id,
        title=file.filename,
        authors="Extracting...",
        abstract="Extracting...",
        file_path=file_path
    )
    database.update_review_status(paper_id, 'pending')
    
    # Start pipeline in the background
    background_tasks.add_task(run_pipeline_task, paper_id, text, None, file_path, model)
    
    return {"paper_id": paper_id, "status": "processing"}

@app.post("/api/import/arxiv")
def import_arxiv(req: ArxivRequest, background_tasks: BackgroundTasks):
    arxiv_id = parse_arxiv_id(req.url_or_id)
    if not arxiv_id:
        raise HTTPException(status_code=400, detail="Invalid arXiv ID or URL")
        
    paper_id = f"arxiv_{arxiv_id.replace('/', '_')}"
    
    # Check if paper already exists
    existing = database.get_paper(paper_id)
    if existing:
        # If review failed, re-run
        review = database.get_review(paper_id)
        if review and review['status'] == 'completed':
            return {"paper_id": paper_id, "status": "exists"}
            
    # Fetch paper
    try:
        title, authors, abstract, pdf_path = fetch_arxiv_metadata_and_pdf(arxiv_id)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve arXiv paper: {str(e)}")
        
    # Save paper to DB
    database.add_paper(
        paper_id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract,
        arxiv_id=arxiv_id,
        file_path=pdf_path
    )
    database.update_review_status(paper_id, 'pending')
    
    # Parse text from PDF
    try:
        text = extract_pdf_text(pdf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract text from downloaded arXiv PDF: {str(e)}")
        
    # Start pipeline in the background
    background_tasks.add_task(run_pipeline_task, paper_id, text, arxiv_id, pdf_path, req.model)
    
    return {"paper_id": paper_id, "status": "processing"}

@app.post("/api/papers/{paper_id}/feedback")
def submit_feedback(paper_id: str, req: FeedbackRequest, background_tasks: BackgroundTasks):
    paper = database.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
        
    review = database.get_review(paper_id)
    if not review or review['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Cannot provide feedback on a paper that hasn't been successfully reviewed.")
        
    logs = database.get_feedback_logs(paper_id)
    
    # Trigger reflection task in background
    background_tasks.add_task(run_reflection_task, paper_id, paper, review, req.feedback, logs, req.model)
    
    return {"status": "processing"}

@app.get("/api/papers/{paper_id}/file")
def get_paper_file(paper_id: str):
    paper = database.get_paper(paper_id)
    if not paper or not paper.get('file_path'):
        raise HTTPException(status_code=404, detail="PDF file not found")
    
    file_path = paper['file_path']
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
        
    return FileResponse(file_path, media_type="application/pdf")

# Serve static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    return FileResponse("static/index.html")
