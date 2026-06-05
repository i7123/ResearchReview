import json
import asyncio
import re
import os
import openai
import aisuite as ai
import contextlib
from datetime import datetime

# Initialize standard aisuite client
client = ai.Client()

DEFAULT_MODEL = "google:gemini-3.5-flash"

@contextlib.asynccontextmanager
async def trace_agent_step(paper_id: str, step_name: str, input_data: dict):
    """Context manager to measure and log execution details of an agent step."""
    import database
    start_time = datetime.now()
    start_iso = start_time.isoformat()
    status = "success"
    error_message = None
    result = {"output": None}
    try:
        yield result
    except Exception as e:
        status = "failed"
        error_message = str(e)
        raise e
    finally:
        end_time = datetime.now()
        end_iso = end_time.isoformat()
        duration = (end_time - start_time).total_seconds()
        
        try:
            input_str = json.dumps(input_data, indent=2)
        except Exception:
            input_str = str(input_data)
            
        try:
            output_str = json.dumps(result["output"], indent=2)
        except Exception:
            output_str = str(result["output"])
            
        database.add_agent_trace(
            paper_id=paper_id,
            step_name=step_name,
            start_time=start_iso,
            end_time=end_iso,
            duration=duration,
            input_data=input_str,
            output_data=output_str,
            status=status,
            error_message=error_message
        )

def clean_json_response(content):
    """Extracts JSON content from markdown code blocks if present, and parses it."""
    content = content.strip()
    # Match markdown code block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
    if match:
        json_str = match.group(1)
    else:
        json_str = content
    
    # Try parsing
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Fallback cleaning for common issues
        try:
            # Try to find first '{' and last '}'
            start = json_str.find('{')
            end = json_str.rfind('}')
            if start != -1 and end != -1:
                return json.loads(json_str[start:end+1])
        except Exception:
            pass
        raise ValueError(f"Failed to parse JSON response: {e}\nRaw output: {content}")

async def run_llm_call(model: str, messages: list, response_format=None) -> str:
    """Runs LLM chat completion (using direct OpenAI client for google: models, and aisuite for others)."""
    def _call():
        target_model = model if model else DEFAULT_MODEL
        
        if target_model.startswith("google:"):
            # Route to Gemini OpenAI-compatible API to support standard API keys
            model_name = target_model.split(":", 1)[1]
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable is not set in .env file.")
                
            openai_client = openai.OpenAI(
                api_key=api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            response = openai_client.chat.completions.create(
                model=model_name,
                messages=messages
            )
            return response.choices[0].message.content
        else:
            # Fallback to standard aisuite client
            response = client.chat.completions.create(
                model=target_model,
                messages=messages
            )
            return response.choices[0].message.content

    return await asyncio.to_thread(_call)

# ==========================================
# AGENT 1: Ingestion & Metadata Extractor
# ==========================================
class IngestionAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def extract_metadata(self, raw_text: str) -> dict:
        # Pass first 60k characters to avoid token limits on smaller context models
        sample_text = raw_text[:60000]
        
        system_prompt = (
            "You are an expert academic metadata extraction agent. Your job is to analyze the "
            "beginning of a research paper and extract its metadata in structured JSON format.\n"
            "Return ONLY a JSON object with these keys:\n"
            "- 'title': The official title of the paper.\n"
            "- 'authors': A single string listing the authors (e.g. 'John Doe, Jane Smith').\n"
            "- 'abstract': The complete abstract text of the paper."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Here is the text from the paper:\n\n{sample_text}"}
        ]
        
        raw_output = await run_llm_call(self.model, messages)
        return clean_json_response(raw_output)

# ==========================================
# AGENT 2: Classification Agent
# ==========================================
class ClassificationAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def classify_paper(self, title: str, abstract: str, categories: list) -> dict:
        category_list_str = "\n".join([
            f"- ID {c['id']}: {c['name']} - {c['description']}" for c in categories
        ])
        
        system_prompt = (
            "You are a scientific research classification agent. Your task is to analyze the "
            "title and abstract of a research paper, and classify it into the most fitting category "
            "from the provided list. If NONE of the existing categories fit, you can suggest a NEW category.\n\n"
            "Return ONLY a JSON object with these keys:\n"
            "- 'category_id': The integer ID of the best matching category (or null if none fit).\n"
            "- 'suggested_category_name': (Only if category_id is null) A concise name for a new category.\n"
            "- 'suggested_category_description': (Only if category_id is null) A brief description of the new category.\n"
            "- 'rationale': A brief sentence explaining your decision."
        )
        
        user_content = (
            f"Title: {title}\n"
            f"Abstract: {abstract}\n\n"
            f"Available Categories:\n{category_list_str}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        raw_output = await run_llm_call(self.model, messages)
        return clean_json_response(raw_output)

# ==========================================
# AGENT 3: Review & Rating Agent
# ==========================================
class ReviewerAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def review_paper(self, title: str, abstract: str, full_text: str, category_name: str) -> dict:
        sample_text = full_text[:80000] # Use up to 80k characters
        
        system_prompt = (
            "You are an elite academic peer reviewer. Analyze the research paper content and write a "
            "thorough, objective, and high-quality peer review. You must evaluate the paper using the "
            "following aspects:\n"
            "1. Strengths: What are the key merits and contributions?\n"
            "2. Weaknesses: What are the main flaws, assumptions, or areas lacking details?\n"
            "3. Novelty: How original is the work compared to existing state-of-the-art?\n"
            "4. Technical Correctness: Are the methodologies, formulas, or logical steps correct?\n"
            "5. Overall Score: Provide an overall rating between 1 and 5 (1=Reject, 2=Weak Accept, 3=Accept, 4=Strong Accept, 5=Outstanding).\n\n"
            "Return ONLY a JSON object with these keys:\n"
            "- 'strengths': A list of string bullet points detailing the strengths.\n"
            "- 'weaknesses': A list of string bullet points detailing the weaknesses.\n"
            "- 'novelty': A thorough paragraph discussing the novelty of the research.\n"
            "- 'technical_correctness': A thorough paragraph discussing the technical correctness.\n"
            "- 'overall_score': An integer rating from 1 to 5."
        )
        
        user_content = (
            f"Paper Title: {title}\n"
            f"Category: {category_name}\n"
            f"Abstract: {abstract}\n\n"
            f"Paper Text Selection:\n{sample_text}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        raw_output = await run_llm_call(self.model, messages)
        return clean_json_response(raw_output)

# ==========================================
# AGENT 4: Feasibility & Manufacturing Agent
# ==========================================
class FeasibilityAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def evaluate_feasibility(self, title: str, full_text: str, category_name: str, review_summary: dict) -> dict:
        sample_text = full_text[:80000]
        
        system_prompt = (
            "You are an industrial engineer and scientific replication specialist. Your task is to evaluate "
            "the feasibility of reproducing the experiment or manufacturing process described in this research paper.\n"
            "You must break down the requirements, steps, and provide concrete recommendations.\n\n"
            "Return ONLY a JSON object with these keys:\n"
            "- 'materials_and_equipment': A list of objects, each with:\n"
            "  * 'name': Name of the material, equipment, chemical, or software required.\n"
            "  * 'purpose': What it is used for.\n"
            "  * 'accessibility': Rating of how easy it is to source (e.g. 'Standard', 'Specialized', 'Very Rare/Custom').\n"
            "- 'estimated_cost': A brief description or estimate of the cost required for replication (e.g. 'Low (<$1,000)', 'Medium ($1,000 - $10,000)', 'High (>$10,000)').\n"
            "- 'replication_steps': A list of string numbered steps detailing the process to repeat the experiment/synthesis/fabrication.\n"
            "- 'recommendations': A detailed paragraph with suggestions, safety warnings, manufacturing readiness level (MRL) assessment, or design alterations for replication."
        )
        
        user_content = (
            f"Paper Title: {title}\n"
            f"Category: {category_name}\n"
            f"Review Summary: {json.dumps(review_summary, indent=2)}\n\n"
            f"Paper Text Selection:\n{sample_text}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        raw_output = await run_llm_call(self.model, messages)
        return clean_json_response(raw_output)

# ==========================================
# AGENT 5: Reflection / Feedback Coordinator Agent
# ==========================================
class ReflectionAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    async def reflect_and_update(self, paper_details: dict, current_review: dict, user_feedback: str, feedback_history: list) -> dict:
        system_prompt = (
            "You are the reflection coordinator for a team of scientific review agents. A user has "
            "provided specific feedback, critique, or new details regarding the current review and feasibility assessment of a paper.\n"
            "Your job is to analyze this feedback alongside the paper's contents and the previous review/feasibility reports, "
            "then output an UPDATED and improved combined review and feasibility report.\n\n"
            "Return ONLY a JSON object with these exact keys:\n"
            "- 'reflection_summary': A brief paragraph explaining what changes you made to incorporate the feedback.\n"
            "- 'review': A dictionary containing the updated review with keys:\n"
            "  * 'strengths' (list of strings)\n"
            "  * 'weaknesses' (list of strings)\n"
            "  * 'novelty' (string)\n"
            "  * 'technical_correctness' (string)\n"
            "  * 'overall_score' (integer 1-5)\n"
            "- 'feasibility': A dictionary containing the updated feasibility report with keys:\n"
            "  * 'materials_and_equipment' (list of objects with 'name', 'purpose', 'accessibility')\n"
            "  * 'estimated_cost' (string)\n"
            "  * 'replication_steps' (list of strings)\n"
            "  * 'recommendations' (string)"
        )
        
        history_str = ""
        if feedback_history:
            history_str = "Prior Feedback History:\n" + "\n".join([
                f"- Feedback: {h['user_feedback']}\n- Reflection: {h['agent_reflection']}" for h in feedback_history
            ])
            
        user_content = (
            f"Paper: {paper_details['title']}\n"
            f"Abstract: {paper_details['abstract']}\n\n"
            f"Current Review: {json.dumps(current_review, indent=2)}\n\n"
            f"{history_str}\n\n"
            f"NEW USER FEEDBACK TO ADDRESS: {user_feedback}\n\n"
            f"Please update the review and feasibility details based on this feedback."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        raw_output = await run_llm_call(self.model, messages)
        return clean_json_response(raw_output)

# ==========================================
# Orchestrator Pipeline Runner
# ==========================================
async def run_full_pipeline(paper_id: str, raw_text: str, arxiv_id: str = None, file_path: str = None, model: str = DEFAULT_MODEL, on_log_callback = None):
    """Orchestrates the running of the metadata, classification, review, and feasibility agents."""
    
    # Imports inside function to avoid circular dependencies
    import database
    
    # Helper for logging progress
    def log(message):
        if on_log_callback:
            on_log_callback(message)
        print(f"[Pipeline Log] {message}")
        
    try:
        # Step 1: Ingestion & Metadata Extractor
        log("Starting Ingestion Agent: Extracting metadata...")
        ingestion = IngestionAgent(model)
        
        async with trace_agent_step(paper_id, "Ingestion & Metadata Extraction", {"raw_text_length": len(raw_text)}) as trace:
            metadata = await ingestion.extract_metadata(raw_text)
            trace["output"] = metadata
            
        log(f"Ingestion complete. Title: '{metadata['title']}'")
        
        # Step 2: Save paper stub to DB so classification can refer to it
        log("Saving paper metadata to database...")
        database.add_paper(
            paper_id=paper_id,
            title=metadata['title'],
            authors=metadata['authors'],
            abstract=metadata['abstract'],
            arxiv_id=arxiv_id,
            file_path=file_path
        )
        
        # Step 3: Classification
        log("Starting Classification Agent: Categorizing paper...")
        classifier = ClassificationAgent(model)
        categories = database.list_categories()
        
        async with trace_agent_step(paper_id, "Paper Classification", {"title": metadata['title'], "categories_available": [c['name'] for c in categories]}) as trace:
            class_res = await classifier.classify_paper(metadata['title'], metadata['abstract'], categories)
            trace["output"] = class_res
        
        category_id = class_res.get('category_id')
        if not category_id:
            # Check if there is a suggested category
            sug_name = class_res.get('suggested_category_name')
            sug_desc = class_res.get('suggested_category_description', '')
            if sug_name:
                log(f"Classifier suggested a new category: '{sug_name}'")
                category_id = database.add_category(sug_name, sug_desc)
                if not category_id:
                    # If conflict occurred, select computer science or any default
                    category_id = categories[0]['id'] if categories else None
        
        if category_id:
            database.update_paper_category(paper_id, category_id)
            paper_data = database.get_paper(paper_id)
            category_name = paper_data.get('category_name', 'General')
            log(f"Paper classified under: '{category_name}'")
        else:
            category_name = "General"
            log("No category matched or suggested.")
            
        # Step 4: Review and Rating
        log("Starting Reviewer Agent: Writing academic peer review...")
        reviewer = ReviewerAgent(model)
        
        async with trace_agent_step(paper_id, "Peer Review Analysis", {"title": metadata['title'], "category": category_name}) as trace:
            review_res = await reviewer.review_paper(metadata['title'], metadata['abstract'], raw_text, category_name)
            trace["output"] = review_res
            
        log(f"Peer review completed. Rating: {review_res['overall_score']}/5")
        
        # Step 5: Feasibility & Manufacturing Recommendation
        log("Starting Feasibility Agent: Assessing reproducibility & manufacturing feasibility...")
        feasibility = FeasibilityAgent(model)
        
        async with trace_agent_step(paper_id, "Replication & Feasibility Advisory", {"title": metadata['title'], "category": category_name, "review_score": review_res.get('overall_score')}) as trace:
            feasibility_res = await feasibility.evaluate_feasibility(metadata['title'], raw_text, category_name, review_res)
            trace["output"] = feasibility_res
            
        log("Feasibility assessment complete.")
        
        # Step 6: Save completed review to Database
        log("Saving final results to the database...")
        database.save_review(
            paper_id=paper_id,
            strengths=json.dumps(review_res.get('strengths', [])),
            weaknesses=json.dumps(review_res.get('weaknesses', [])),
            novelty=review_res.get('novelty', ''),
            technical_correctness=review_res.get('technical_correctness', ''),
            overall_score=review_res.get('overall_score', 3),
            feasibility_report=json.dumps(feasibility_res),
            status='completed'
        )
        log("Full pipeline completed successfully.")
        return True
        
    except Exception as e:
        log(f"Error in pipeline: {str(e)}")
        database.update_review_status(paper_id, 'failed')
        # Also ensure paper is recorded if possible
        raise e
