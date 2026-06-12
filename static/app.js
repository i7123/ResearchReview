// App State
let categories = [];
let papers = [];
let selectedPaperId = null;
let activeWorkspaceTab = 'logs'; // logs, review, feasibility, reflection, traces
let activeImportTab = 'arxiv'; // arxiv, upload
let selectedFile = null;
let selectedFiles = [];
let logPollInterval = null;
let globalPollInterval = null;
let currentTraces = [];

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    init();
});

function init() {
    fetchCategories();
    fetchPapers();
    setupDragAndDrop();
    
    // Periodically poll all papers to catch updates from the background
    globalPollInterval = setInterval(() => {
        fetchPapers(false); // Silent fetch, don't disrupt selection
    }, 5000);
}

// Drag & Drop Setup
function setupDragAndDrop() {
    const dropZone = document.getElementById('drop-zone');
    if (!dropZone) return;

    // Open file dialog on click
    dropZone.addEventListener('click', () => {
        document.getElementById('file-input').click();
    });

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFiles(e.dataTransfer.files);
        }
    });
}

function handleFileSelect(e) {
    if (e.target.files.length > 0) {
        handleFiles(e.target.files);
    }
}

function handleFiles(fileList) {
    const validFiles = [];
    for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i];
        if (file.type === 'application/pdf') {
            validFiles.push(file);
        }
    }
    
    if (validFiles.length === 0) {
        alert('Please select valid PDF documents.');
        return;
    }
    
    selectedFiles = validFiles;
    const dropZone = document.getElementById('drop-zone');
    
    if (selectedFiles.length === 1) {
        const file = selectedFiles[0];
        dropZone.querySelector('p').innerHTML = `Selected: <strong>${escapeHTML(file.name)}</strong> (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
    } else {
        dropZone.querySelector('p').innerHTML = `Selected: <strong>${selectedFiles.length} PDF files</strong>`;
    }
    
    document.getElementById('btn-import-upload').removeAttribute('disabled');
}

// Sidebar Navigation & Tabs
function switchImportTab(tab) {
    activeImportTab = tab;
    document.getElementById('btn-tab-arxiv').classList.toggle('active', tab === 'arxiv');
    document.getElementById('btn-tab-upload').classList.toggle('active', tab === 'upload');
    
    document.getElementById('import-arxiv-panel').classList.toggle('active', tab === 'arxiv');
    document.getElementById('import-upload-panel').classList.toggle('active', tab === 'upload');
}

function switchWorkspaceTab(tab) {
    activeWorkspaceTab = tab;
    
    // Toggle active classes on buttons
    const tabLinks = document.querySelectorAll('.tab-link');
    tabLinks.forEach(link => {
        const isMatch = link.getAttribute('onclick').includes(tab);
        link.classList.toggle('active', isMatch);
    });
    
    // Toggle active classes on panes
    document.getElementById('pane-logs').classList.toggle('active', tab === 'logs');
    document.getElementById('pane-review').classList.toggle('active', tab === 'review');
    document.getElementById('pane-feasibility').classList.toggle('active', tab === 'feasibility');
    document.getElementById('pane-reflection').classList.toggle('active', tab === 'reflection');
    document.getElementById('pane-traces').classList.toggle('active', tab === 'traces');

    if (tab === 'traces' && selectedPaperId) {
        loadTraces(selectedPaperId);
    }
}

// Fetch categories from API
async function fetchCategories() {
    try {
        const res = await fetch('/api/categories');
        if (!res.ok) throw new Error('Failed to load categories');
        categories = await res.json();
        renderCategories();
    } catch (err) {
        console.error(err);
    }
}

function renderCategories() {
    const container = document.getElementById('categories-container');
    if (!container) return;
    
    container.innerHTML = categories.map(cat => `
        <span class="cat-item" onclick="filterPapersByCategory(${cat.id})">${cat.name}</span>
    `).join('');
}

// Fetch Papers list from API
async function fetchPapers(updateSelected = true) {
    try {
        const res = await fetch('/api/papers');
        if (!res.ok) throw new Error('Failed to load papers');
        papers = await res.json();
        renderPapers();
        
        // If a paper was selected, refresh its details silently to see if status updated
        if (selectedPaperId && updateSelected) {
            const currentSelected = papers.find(p => p.id === selectedPaperId);
            if (currentSelected) {
                // If it transitioned out of processing/pending, refresh the workspace
                const wasProcessing = document.getElementById('log-status').classList.contains('processing');
                const isProcessingNow = currentSelected.review_status === 'processing' || currentSelected.review_status === 'pending';
                
                if (wasProcessing && !isProcessingNow) {
                    selectPaper(selectedPaperId);
                }
            }
        }
    } catch (err) {
        console.error(err);
    }
}

function renderPapers() {
    const container = document.getElementById('papers-container');
    if (!container) return;
    
    if (papers.length === 0) {
        container.innerHTML = `<p style="font-size: 12px; color: var(--text-muted); text-align: center; margin-top: 20px;">No papers imported yet.</p>`;
        return;
    }
    
    container.innerHTML = papers.map(paper => {
        const score = paper.overall_score ? `<span class="paper-item-score-badge"><i class="fa-solid fa-star"></i> ${paper.overall_score}/5</span>` : '';
        const categoryTag = paper.category_name ? `<span class="paper-item-tag">${paper.category_name}</span>` : '<span class="paper-item-tag">Uncategorized</span>';
        const isSelected = paper.id === selectedPaperId ? 'selected' : '';
        
        let statusBadge = '';
        if (paper.review_status !== 'completed') {
            const statusClass = paper.review_status || 'pending';
            statusBadge = `<span class="status-badge ${statusClass}">${statusClass}</span>`;
        }
        
        return `
            <div class="paper-item ${isSelected}" onclick="selectPaper('${paper.id}')">
                <button class="btn-delete-paper" onclick="deletePaper('${paper.id}', event)" title="Delete Paper">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
                <div class="paper-item-title">${escapeHTML(paper.title)}</div>
                <div class="paper-item-authors">${escapeHTML(paper.authors || 'Unknown Authors')}</div>
                <div class="paper-item-meta">
                    ${categoryTag}
                    ${statusBadge || score}
                </div>
            </div>
        `;
    }).join('');
}

async function deletePaper(paperId, event) {
    if (event) {
        event.stopPropagation();
    }
    
    if (!confirm("Are you sure you want to delete this paper and all its associated reviews/traces?")) {
        return;
    }
    
    try {
        const res = await fetch(`/api/papers/${paperId}`, {
            method: 'DELETE'
        });
        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || 'Failed to delete paper');
        }
        
        // If the deleted paper was selected, clear selection
        if (selectedPaperId === paperId) {
            selectedPaperId = null;
            document.getElementById('paper-workspace').style.display = 'none';
            document.getElementById('empty-state').style.display = 'flex';
        }
        
        // Refresh paper list
        fetchPapers();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// Filter Papers in library by Search Term
function filterPapers() {
    const query = document.getElementById('library-search').value.toLowerCase();
    const paperItems = document.querySelectorAll('.paper-item');
    
    papers.forEach((paper, index) => {
        const titleMatch = paper.title.toLowerCase().includes(query);
        const authorMatch = (paper.authors || '').toLowerCase().includes(query);
        const categoryMatch = (paper.category_name || '').toLowerCase().includes(query);
        
        const isVisible = titleMatch || authorMatch || categoryMatch;
        if (paperItems[index]) {
            paperItems[index].style.display = isVisible ? 'flex' : 'none';
        }
    });
}

function filterPapersByCategory(catId) {
    // If clicking an active category badge, clear filter
    const activeBadge = document.querySelector(`.cat-item.active`);
    const clickedBadge = event.target;
    
    document.querySelectorAll('.cat-item').forEach(b => b.classList.remove('active'));
    
    if (activeBadge === clickedBadge) {
        // Clear filter
        document.getElementById('library-search').value = '';
        filterPapers();
    } else {
        clickedBadge.classList.add('active');
        const cat = categories.find(c => c.id === catId);
        if (cat) {
            document.getElementById('library-search').value = cat.name;
            filterPapers();
        }
    }
}

// Select a Paper
async function selectPaper(paperId) {
    selectedPaperId = paperId;
    
    // Highlight paper in sidebar list
    document.querySelectorAll('.paper-item').forEach(item => {
        item.classList.toggle('selected', item.getAttribute('onclick').includes(paperId));
    });
    
    // Reset trace UI for the newly selected paper
    resetTraceUI();
    
    // Show loading indicator
    showGlobalLoading("Retrieving document evaluations...");
    
    try {
        const res = await fetch(`/api/papers/${paperId}`);
        if (!res.ok) throw new Error('Failed to load paper details');
        const details = await res.json();
        
        hideGlobalLoading();
        
        // Display Paper Panel
        document.getElementById('empty-state').style.display = 'none';
        document.getElementById('paper-workspace').style.display = 'flex';
        
        // Render basic metadata
        const paper = details.paper;
        document.getElementById('paper-display-title').textContent = paper.title;
        document.getElementById('paper-display-authors').textContent = paper.authors || 'Unknown';
        document.getElementById('paper-display-abstract').textContent = paper.abstract || 'No abstract text available.';
        
        const categoryBadge = document.getElementById('paper-category-badge');
        categoryBadge.textContent = paper.category_name || 'PENDING CLASSIFICATION';
        categoryBadge.style.display = paper.category_name ? 'inline-block' : 'inline-block';
        
        const dateObj = new Date(paper.created_at);
        document.getElementById('paper-display-date').innerHTML = `<i class="fa-solid fa-calendar-days"></i> Added ${dateObj.toLocaleDateString()}`;
        
        const arxivSpan = document.getElementById('paper-display-arxiv');
        if (paper.arxiv_id) {
            arxivSpan.innerHTML = `<i class="fa-solid fa-link"></i> arXiv:${paper.arxiv_id}`;
            arxivSpan.style.display = 'inline';
        } else {
            arxivSpan.style.display = 'none';
        }
        
        const pdfLink = document.getElementById('paper-pdf-link');
        if (paper.file_path) {
            pdfLink.href = `/api/papers/${paperId}/file`; // Note: we can let FastAPI serve the direct file or just point to a placeholder
            pdfLink.style.display = 'inline-flex';
            // Actually, we'll hook up static files in a simpler way, or keep it as download URL.
            // Let's just point to a placeholder or hide if we don't have a direct file viewer
            pdfLink.href = "#";
            pdfLink.onclick = (e) => { e.preventDefault(); alert("PDF path: " + paper.file_path); };
        } else {
            pdfLink.style.display = 'none';
        }
        
        // Set up tab contents
        const review = details.review;
        const statusIndicator = document.getElementById('log-status');
        
        if (review) {
            statusIndicator.textContent = review.status;
            statusIndicator.className = `status-indicator ${review.status}`;
            
            // Clear prior intervals
            if (logPollInterval) clearInterval(logPollInterval);
            
            if (review.status === 'processing' || review.status === 'pending') {
                // In progress. Lock tabs and switch to logs
                document.getElementById('tab-btn-review').setAttribute('disabled', 'true');
                document.getElementById('tab-btn-feasibility').setAttribute('disabled', 'true');
                document.getElementById('tab-btn-reflection').setAttribute('disabled', 'true');
                switchWorkspaceTab('logs');
                
                // Start polling logs
                startLogPolling(paperId);
            } else if (review.status === 'completed') {
                // Completed. Unlock tabs
                document.getElementById('tab-btn-review').removeAttribute('disabled');
                document.getElementById('tab-btn-feasibility').removeAttribute('disabled');
                document.getElementById('tab-btn-reflection').removeAttribute('disabled');
                
                // Switch tabs back to Review if we were in logs, or keep current
                if (activeWorkspaceTab === 'logs') {
                    switchWorkspaceTab('review');
                }
                
                // Render review data
                renderReviewData(review);
                
                // Render feasibility data
                renderFeasibilityData(review.feasibility_report);
                
                // Render reflection loop
                renderReflectionData(details.feedback_logs);
            } else {
                // Failed
                document.getElementById('tab-btn-review').setAttribute('disabled', 'true');
                document.getElementById('tab-btn-feasibility').setAttribute('disabled', 'true');
                document.getElementById('tab-btn-reflection').setAttribute('disabled', 'true');
                switchWorkspaceTab('logs');
            }
        } else {
            statusIndicator.textContent = 'pending';
            statusIndicator.className = 'status-indicator pending';
            startLogPolling(paperId);
        }
        
        // Load logs initially
        loadLogs(paperId);
        
        // Load traces initially if we are currently on traces tab
        if (activeWorkspaceTab === 'traces') {
            loadTraces(paperId);
        }
        
    } catch (err) {
        hideGlobalLoading();
        alert(err.message);
    }
}

// Polling Paper Logs during execution
function startLogPolling(paperId) {
    if (logPollInterval) clearInterval(logPollInterval);
    
    logPollInterval = setInterval(async () => {
        const isCompleted = await loadLogs(paperId);
        
        // If the user is viewing the traces tab, refresh traces too
        if (activeWorkspaceTab === 'traces') {
            loadTraces(paperId);
        }
        
        if (isCompleted) {
            clearInterval(logPollInterval);
            // Refresh full paper details
            selectPaper(paperId);
            fetchPapers(false);
        }
    }, 1500);
}

async function loadLogs(paperId) {
    const consoleBox = document.getElementById('log-console-content');
    if (!consoleBox) return false;
    
    try {
        const res = await fetch(`/api/papers/${paperId}/logs`);
        if (!res.ok) return false;
        const data = await res.json();
        
        const logs = data.logs || [];
        
        if (logs.length === 0) {
            consoleBox.innerHTML = `<div class="log-entry system">[Waiting for agent coordination initialization...]</div>`;
        } else {
            consoleBox.innerHTML = logs.map(line => {
                const isAgent = line.startsWith('Starting') || line.includes('Agent:');
                const isErr = line.includes('failed') || line.includes('Error');
                const lineClass = isErr ? 'log-entry negative' : (isAgent ? 'log-entry agent' : 'log-entry system');
                return `<div class="${lineClass}">${escapeHTML(line)}</div>`;
            }).join('');
        }
        
        // Auto Scroll to bottom
        consoleBox.scrollTop = consoleBox.scrollHeight;
        
        // Check if logs indicate completion or failure
        const hasFinished = logs.some(line => line.includes('completed successfully') || line.includes('failed') || line.includes('Reflection completed'));
        return hasFinished;
    } catch (err) {
        console.error(err);
        return false;
    }
}

// Render review fields
function renderReviewData(review) {
    document.getElementById('review-score').textContent = review.overall_score || '?';
    
    // Render stars
    const starsContainer = document.getElementById('review-stars');
    let starHTML = '';
    const score = review.overall_score || 0;
    for (let i = 1; i <= 5; i++) {
        if (i <= score) {
            starHTML += `<i class="fa-solid fa-star"></i>`;
        } else {
            starHTML += `<i class="fa-regular fa-star"></i>`;
        }
    }
    starsContainer.innerHTML = starHTML;
    
    // Strengths & Weaknesses
    let strengths = [];
    let weaknesses = [];
    try {
        strengths = JSON.parse(review.strengths || '[]');
    } catch (e) {
        strengths = review.strengths ? [review.strengths] : [];
    }
    try {
        weaknesses = JSON.parse(review.weaknesses || '[]');
    } catch (e) {
        weaknesses = review.weaknesses ? [review.weaknesses] : [];
    }
    
    document.getElementById('review-strengths').innerHTML = strengths.map(s => `<li>${escapeHTML(s)}</li>`).join('') || '<li>No specific strengths recorded.</li>';
    document.getElementById('review-weaknesses').innerHTML = weaknesses.map(w => `<li>${escapeHTML(w)}</li>`).join('') || '<li>No specific weaknesses recorded.</li>';
    
    // Paragraph text
    document.getElementById('review-novelty').textContent = review.novelty || 'No novelty assessment available.';
    document.getElementById('review-correctness').textContent = review.technical_correctness || 'No technical correctness assessment available.';
}

// Render replication feasibility fields
function renderFeasibilityData(reportStr) {
    if (!reportStr) {
        document.getElementById('feasibility-cost').textContent = 'N/A';
        document.getElementById('feasibility-materials-body').innerHTML = `<tr><td colspan="3">No feasibility data provided.</td></tr>`;
        document.getElementById('feasibility-steps').innerHTML = `<li>No workflow provided.</li>`;
        document.getElementById('feasibility-advisory').textContent = 'No advisory available.';
        return;
    }
    
    let report = {};
    try {
        report = typeof reportStr === 'string' ? JSON.parse(reportStr) : reportStr;
    } catch (e) {
        console.error("Failed to parse feasibility report JSON:", e);
        return;
    }
    
    document.getElementById('feasibility-cost').textContent = report.estimated_cost || 'Unknown';
    
    // Sourcing table
    const materials = report.materials_and_equipment || [];
    const tableBody = document.getElementById('feasibility-materials-body');
    if (materials.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="3">No items listed.</td></tr>`;
    } else {
        tableBody.innerHTML = materials.map(item => `
            <tr>
                <td><strong>${escapeHTML(item.name)}</strong></td>
                <td>${escapeHTML(item.purpose || 'N/A')}</td>
                <td><span class="status-badge ${getAccessibilityClass(item.accessibility)}">${escapeHTML(item.accessibility)}</span></td>
            </tr>
        `).join('');
    }
    
    // Replication Steps
    const steps = report.replication_steps || [];
    document.getElementById('feasibility-steps').innerHTML = steps.map(step => `
        <li>${escapeHTML(step)}</li>
    `).join('') || '<li>No replication steps described.</li>';
    
    // Advisory
    document.getElementById('feasibility-advisory').textContent = report.recommendations || 'No specific safety warnings or recommendations.';
}

function getAccessibilityClass(level) {
    if (!level) return 'pending';
    const l = level.toLowerCase();
    if (l.includes('standard') || l.includes('easy')) return 'completed';
    if (l.includes('specialized') || l.includes('medium')) return 'processing';
    return 'failed'; // Custom or rare
}

// Render reflection history timeline
function renderReflectionData(logs) {
    const container = document.getElementById('reflection-timeline-container');
    if (!container) return;
    
    if (!logs || logs.length === 0) {
        container.innerHTML = `<p style="font-size: 12px; color: var(--text-muted); font-style: italic;">No reflection iterations have occurred yet. You can submit feedback below to refine the agent assessments.</p>`;
        return;
    }
    
    container.innerHTML = logs.map((log, index) => {
        const dateObj = new Date(log.created_at);
        return `
            <div class="reflection-card">
                <div class="reflection-header">
                    <span>Iteration #${index + 1}</span>
                    <span>${dateObj.toLocaleString()}</span>
                </div>
                <div class="reflection-body">
                    <div class="reflection-query">
                        <strong>User Feedback:</strong>
                        <p>${escapeHTML(log.user_feedback)}</p>
                    </div>
                    <div class="reflection-response">
                        <strong>Reflection Agent Decision:</strong>
                        <p>${escapeHTML(log.agent_reflection)}</p>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.scrollTop = container.scrollHeight;
}

// Core Operations: Import ArXiv
async function importFromArxiv() {
    const input = document.getElementById('arxiv-input');
    const val = input.value.strip ? input.value.strip() : input.value.trim();
    if (!val) {
        alert('Please enter an arXiv ID or abstract URL.');
        return;
    }
    
    const model = document.getElementById('global-model-select').value;
    
    showGlobalLoading("Querying arXiv feed and downloading document...");
    
    try {
        const res = await fetch('/api/import/arxiv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url_or_id: val, model: model })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to import from arXiv');
        
        input.value = '';
        hideGlobalLoading();
        
        // Reload library & Select the new paper
        await fetchPapers(false);
        selectPaper(data.paper_id);
        
    } catch (err) {
        hideGlobalLoading();
        alert(err.message);
    }
}

// Core Operations: Upload PDF (supports batch uploads)
async function uploadPDF() {
    if (selectedFiles.length === 0) return;
    
    const model = document.getElementById('global-model-select').value;
    const dropZone = document.getElementById('drop-zone');
    
    let lastPaperId = null;
    let successCount = 0;
    let failCount = 0;
    
    showGlobalLoading(`Processing 1 of ${selectedFiles.length} files...`);
    
    for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        showGlobalLoading(`Processing file ${i + 1} of ${selectedFiles.length}: ${file.name}...`);
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('model', model);
        
        try {
            const res = await fetch('/api/import/pdf', {
                method: 'POST',
                body: formData
            });
            
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `Failed to upload ${file.name}`);
            
            lastPaperId = data.paper_id;
            successCount++;
        } catch (err) {
            console.error(err);
            failCount++;
        }
    }
    
    // Reset file select UI
    selectedFiles = [];
    dropZone.querySelector('p').innerHTML = `Drag PDF(s) here, or <span>browse</span>`;
    document.getElementById('btn-import-upload').setAttribute('disabled', 'true');
    
    hideGlobalLoading();
    
    if (failCount > 0) {
        alert(`Batch upload complete. Successfully processed: ${successCount} files. Failed: ${failCount} files.`);
    }
    
    // Reload Library & Select the last processed paper
    await fetchPapers(false);
    if (lastPaperId) {
        selectPaper(lastPaperId);
    }
}

// Core Operations: Submit User Feedback for reflection
async function submitFeedback() {
    const feedbackBox = document.getElementById('feedback-textarea');
    const text = feedbackBox.value.trim();
    if (!text) {
        alert('Please write some feedback before submitting.');
        return;
    }
    
    if (!selectedPaperId) return;
    
    const model = document.getElementById('global-model-select').value;
    
    // Clear textarea
    feedbackBox.value = '';
    
    // Switch to logs tab and set in progress state
    switchWorkspaceTab('logs');
    document.getElementById('log-status').textContent = 'processing';
    document.getElementById('log-status').className = 'status-indicator processing';
    
    // Lock tab buttons
    document.getElementById('tab-btn-review').setAttribute('disabled', 'true');
    document.getElementById('tab-btn-feasibility').setAttribute('disabled', 'true');
    document.getElementById('tab-btn-reflection').setAttribute('disabled', 'true');
    
    try {
        const res = await fetch(`/api/papers/${selectedPaperId}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback: text, model: model })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to submit feedback');
        
        // Begin log polling to watch reflection updates
        startLogPolling(selectedPaperId);
        
    } catch (err) {
        alert(err.message);
        selectPaper(selectedPaperId);
    }
}

// Core Operations: Taxonomies (Custom Categories)
async function createCategory() {
    const nameInput = document.getElementById('modal-cat-name');
    const descInput = document.getElementById('modal-cat-desc');
    const name = nameInput.value.trim();
    const desc = descInput.value.trim();
    
    if (!name) {
        alert('Category name is required.');
        return;
    }
    
    try {
        const res = await fetch('/api/categories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, description: desc })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to create category');
        
        nameInput.value = '';
        descInput.value = '';
        closeAddCategoryModal();
        
        // Refresh categories
        await fetchCategories();
        
    } catch (err) {
        alert(err.message);
    }
}

// Modal Toggle Helpers
function openAddCategoryModal() {
    document.getElementById('category-modal').classList.add('active');
}

function closeAddCategoryModal() {
    document.getElementById('category-modal').classList.remove('active');
}

// Global UI Overlay Loading
function showGlobalLoading(message) {
    document.getElementById('global-loading-text').textContent = message || "Processing paper pipeline...";
    document.getElementById('global-loading').style.display = 'flex';
}

function hideGlobalLoading() {
    document.getElementById('global-loading').style.display = 'none';
}

// HTML Escaping Utility
function escapeHTML(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// Tracing System Operations
function resetTraceUI() {
    const container = document.getElementById('traces-timeline-container');
    if (container) container.innerHTML = '';
    resetTraceDetails();
}

function resetTraceDetails() {
    const detailsPanel = document.getElementById('trace-details-panel');
    if (detailsPanel) {
        detailsPanel.innerHTML = `
            <div class="empty-trace-details">
                <i class="fa-solid fa-code-branch"></i>
                <p>Select an agent step from the timeline to view detailed inputs, outputs, and execution telemetry.</p>
            </div>
        `;
    }
}

async function loadTraces(paperId) {
    const container = document.getElementById('traces-timeline-container');
    if (!container) return;
    
    try {
        const res = await fetch(`/api/papers/${paperId}/traces`);
        if (!res.ok) throw new Error('Failed to load agent traces');
        currentTraces = await res.json();
        
        if (currentTraces.length === 0) {
            container.innerHTML = `<p style="font-size: 12px; color: var(--text-muted); font-style: italic; padding: 10px 0;">No trace spans recorded yet.</p>`;
            resetTraceDetails();
            return;
        }
        
        container.innerHTML = currentTraces.map((trace, index) => {
            const dateObj = new Date(trace.start_time);
            const statusClass = trace.status === 'success' ? 'success' : 'failed';
            const durationText = trace.duration ? `${trace.duration.toFixed(2)}s` : 'N/A';
            const timeText = dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            
            return `
                <div class="trace-node ${statusClass}" id="trace-node-${trace.id}" onclick="selectTraceNode(${index})">
                    <div class="trace-node-header">
                        <span class="trace-node-name">${escapeHTML(trace.step_name)}</span>
                        <span class="trace-node-duration">${durationText}</span>
                    </div>
                    <div class="trace-node-time"><i class="fa-regular fa-clock"></i> ${timeText}</div>
                </div>
            `;
        }).join('');
        
    } catch (err) {
        console.error(err);
        container.innerHTML = `<p style="font-size: 12px; color: var(--color-negative); font-style: italic;">Error loading traces.</p>`;
    }
}

function selectTraceNode(index) {
    const trace = currentTraces[index];
    if (!trace) return;
    
    // Highlight active node
    document.querySelectorAll('.trace-node').forEach(node => {
        node.classList.remove('active');
    });
    const activeNode = document.getElementById(`trace-node-${trace.id}`);
    if (activeNode) {
        activeNode.classList.add('active');
    }
    
    // Populate details panel
    renderTraceDetails(trace);
}

function renderTraceDetails(trace) {
    const detailsPanel = document.getElementById('trace-details-panel');
    if (!detailsPanel) return;
    
    const startTimeStr = new Date(trace.start_time).toLocaleString();
    const durationText = trace.duration ? `${trace.duration.toFixed(2)} seconds` : 'N/A';
    
    let statusClass = 'pending';
    if (trace.status === 'success') statusClass = 'completed';
    if (trace.status === 'failed') statusClass = 'failed';
    
    // Handle error message block if failed
    const errorBlock = trace.error_message ? `
        <div class="trace-data-section">
            <h4 style="color: var(--color-negative);"><i class="fa-solid fa-circle-exclamation"></i> Error Details</h4>
            <div class="json-block" style="background-color: var(--color-negative-bg); border-color: rgba(158, 42, 43, 0.2); color: var(--color-negative);">
                ${escapeHTML(trace.error_message)}
            </div>
        </div>
    ` : '';
    
    // Format input/output data
    let inputJsonStr = '';
    try {
        inputJsonStr = typeof trace.input_data === 'string' ? trace.input_data : JSON.stringify(trace.input_data, null, 2);
    } catch (e) {
        inputJsonStr = String(trace.input_data);
    }
    
    let outputJsonStr = '';
    try {
        outputJsonStr = typeof trace.output_data === 'string' ? trace.output_data : JSON.stringify(trace.output_data, null, 2);
    } catch (e) {
        outputJsonStr = String(trace.output_data);
    }
    
    detailsPanel.innerHTML = `
        <div class="trace-details-header">
            <div class="trace-details-title">${escapeHTML(trace.step_name)}</div>
            <div class="trace-meta-grid">
                <div class="trace-meta-item">
                    <div class="trace-meta-label">Execution Status</div>
                    <div class="trace-meta-val"><span class="status-badge ${statusClass}">${escapeHTML(trace.status)}</span></div>
                </div>
                <div class="trace-meta-item">
                    <div class="trace-meta-label">Latency / Duration</div>
                    <div class="trace-meta-val">${durationText}</div>
                </div>
                <div class="trace-meta-item">
                    <div class="trace-meta-label">Started At</div>
                    <div class="trace-meta-val">${startTimeStr}</div>
                </div>
            </div>
        </div>
        
        ${errorBlock}
        
        <div class="trace-data-section">
            <h4><i class="fa-solid fa-arrow-right-to-bracket"></i> Agent Step Input</h4>
            <pre class="json-block"><code>${escapeHTML(inputJsonStr)}</code></pre>
        </div>
        
        <div class="trace-data-section">
            <h4><i class="fa-solid fa-arrow-right-from-bracket"></i> Agent Step Output</h4>
            <pre class="json-block"><code>${escapeHTML(outputJsonStr)}</code></pre>
        </div>
    `;
}

function exportLibraryCSV() {
    window.location.href = '/api/export/csv';
}
