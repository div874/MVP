// Script is at bottom of <body> — DOM is already fully parsed, no DOMContentLoaded needed
(function () {
    console.log('[App] Script executing, DOM ready.');

    try {
        // Tab switching elements
        const tabFileUpload = document.getElementById('tabFileUpload');
        const tabUrlUpload = document.getElementById('tabUrlUpload');
        const tabMultiUrlUpload = document.getElementById('tabMultiUrlUpload');

        const fileTabContent = document.getElementById('fileTabContent');
        const urlTabContent = document.getElementById('urlTabContent');
        const multiUrlTabContent = document.getElementById('multiUrlTabContent');

        // File input elements
        const dropzone = document.getElementById('dropzone');
        const reelFileInput = document.getElementById('reelFileInput');
        const dropzoneContent = document.getElementById('dropzoneContent');
        const previewContainer = document.getElementById('previewContainer');
        const videoPreview = document.getElementById('videoPreview');
        const fileName = document.getElementById('fileName');
        const fileMeta = document.getElementById('fileMeta');
        const btnChangeFile = document.getElementById('btnChangeFile');

        // URL input elements
        const reelUrlInput = document.getElementById('reelUrlInput');
        const reelMultiUrlInput = document.getElementById('reelMultiUrlInput');

        // Caption & Form elements
        const reelCaption = document.getElementById('reelCaption');
        const form = document.getElementById('reelUploadForm');
        const btnSubmit = document.getElementById('btnSubmit');
        const statusBanner = document.getElementById('statusBanner');
        const statusMessage = document.getElementById('statusMessage');

        let activeTab = 'file';
        let currentFile = null;

        const API_URL = 'http://localhost:8000/api/upload-reel';

        function formatBytes(bytes, decimals = 2) {
            if (!bytes || bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
        }

        function switchTab(mode) {
            activeTab = mode;
            [tabFileUpload, tabUrlUpload, tabMultiUrlUpload].forEach(t => t && t.classList.remove('active'));
            [fileTabContent, urlTabContent, multiUrlTabContent].forEach(c => c && c.classList.add('hidden'));

            if (mode === 'file') {
                if (tabFileUpload) tabFileUpload.classList.add('active');
                if (fileTabContent) fileTabContent.classList.remove('hidden');
                if (btnSubmit) btnSubmit.querySelector('.btn-text').textContent = 'Analyze Reel';
            } else if (mode === 'url') {
                if (tabUrlUpload) tabUrlUpload.classList.add('active');
                if (urlTabContent) urlTabContent.classList.remove('hidden');
                if (btnSubmit) btnSubmit.querySelector('.btn-text').textContent = 'Analyze Reel';
            } else if (mode === 'multi_url') {
                if (tabMultiUrlUpload) tabMultiUrlUpload.classList.add('active');
                if (multiUrlTabContent) multiUrlTabContent.classList.remove('hidden');
                if (btnSubmit) btnSubmit.querySelector('.btn-text').textContent = 'Analyze Multiple Reels →';
            }
            if (statusBanner) statusBanner.classList.add('hidden');
        }

        if (tabFileUpload) tabFileUpload.addEventListener('click', () => switchTab('file'));
        if (tabUrlUpload) tabUrlUpload.addEventListener('click', () => switchTab('url'));
        if (tabMultiUrlUpload) tabMultiUrlUpload.addEventListener('click', () => switchTab('multi_url'));

        function handleFileSelect(file) {
            if (!file) return;
            const isVideoMime = file.type && file.type.startsWith('video/');
            const isVideoExt = /\.(mp4|mov|webm|mkv|avi|quicktime)$/i.test(file.name);
            if (!isVideoMime && !isVideoExt) {
                alert('Please select a valid video file (MP4, MOV, WEBM).');
                return;
            }
            currentFile = file;
            videoPreview.src = URL.createObjectURL(file);
            fileName.textContent = file.name;
            fileMeta.textContent = formatBytes(file.size);
            dropzoneContent.classList.add('hidden');
            previewContainer.classList.remove('hidden');
            if (statusBanner) statusBanner.classList.add('hidden');
        }

        function resetFileInput() {
            currentFile = null;
            reelFileInput.value = '';
            if (videoPreview.src) {
                URL.revokeObjectURL(videoPreview.src);
                videoPreview.removeAttribute('src');
            }
            previewContainer.classList.add('hidden');
            dropzoneContent.classList.remove('hidden');
            if (statusBanner) statusBanner.classList.add('hidden');
        }

        if (reelFileInput) {
            reelFileInput.addEventListener('change', (e) => {
                if (e.target.files && e.target.files[0]) handleFileSelect(e.target.files[0]);
            });
        }

        if (dropzone) {
            ['dragenter', 'dragover'].forEach(evt => {
                dropzone.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); dropzone.classList.add('drag-active'); }, false);
            });
            ['dragleave', 'drop'].forEach(evt => {
                dropzone.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); dropzone.classList.remove('drag-active'); }, false);
            });
            dropzone.addEventListener('drop', (e) => {
                const files = e.dataTransfer.files;
                if (files && files[0]) { reelFileInput.files = files; handleFileSelect(files[0]); }
            });
        }

        const btnBrowse = document.getElementById('btnBrowse');
        if (btnBrowse) {
            btnBrowse.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); reelFileInput.click(); });
        }

        if (btnChangeFile) {
            btnChangeFile.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); resetFileInput(); reelFileInput.click(); });
        }

        // Variables to store context for the chatbot
        let currentReelsContext = [];
        let currentReportContext = {};

        // Core Analyze Handler
        async function handleAnalyze(e) {
            if (e) e.preventDefault();
            console.log('[App] Analyze triggered.');

            const formData = new FormData();
            const captionValue = reelCaption ? reelCaption.value.trim() : '';

            if (activeTab === 'file') {
                if (!currentFile) { alert('Please select or drag a video file to analyze.'); return; }
                formData.append('file', currentFile);
            } else if (activeTab === 'url') {
                const urlVal = reelUrlInput ? reelUrlInput.value.trim() : '';
                if (!urlVal) { alert('Please enter a valid Reel URL to analyze.'); return; }
                formData.append('url', urlVal);
            } else if (activeTab === 'multi_url') {
                const rawMulti = reelMultiUrlInput ? reelMultiUrlInput.value.trim() : '';
                const urlLines = rawMulti.split('\n').map(l => l.trim()).filter(l => l.startsWith('http'));
                if (urlLines.length === 0) { alert('Please paste at least one valid Reel link (starting with http:// or https://).'); return; }
                formData.append('urls', urlLines.join('\n'));
            }

            if (captionValue) formData.append('caption', captionValue);

            if (btnSubmit) {
                btnSubmit.classList.add('loading');
                btnSubmit.querySelector('.btn-text').textContent = activeTab === 'multi_url' ? 'Analyzing Batch Reels in Parallel...' : 'Uploading to API...';
            }

            const chatSection = document.getElementById('chatSection');
            if (chatSection) chatSection.classList.add('hidden');

            try {
                const response = await fetch(API_URL, { method: 'POST', body: formData });
                if (!response.ok) throw new Error(`Server returned status ${response.status}`);

                const data = await response.json();
                console.log('[App] API response:', data);

                // Save context for chatbot
                currentReelsContext = data.reels || [];
                currentReportContext = data.content_learnings || {};

                const statusBadge = document.getElementById('statusBadge');
                const statusModel = document.getElementById('statusModel');
                const statusFooter = document.getElementById('statusFooter');

                if (statusBanner) statusBanner.classList.remove('hidden');

                if (data.status === 'success') {
                    if (chatSection) chatSection.classList.remove('hidden');
                    const batchCount = data.batch_count || (data.reels ? data.reels.length : 1);
                    if (statusBadge) {
                        statusBadge.textContent = batchCount > 1 
                            ? `✦ Processed ${data.reels?.filter(r=>r.success).length || batchCount} of ${batchCount} Reference Reels`
                            : '✦ Content Intelligence Complete';
                    }
                    if (statusModel) statusModel.textContent = data.ai_analysis?.model || 'Multimodal Vision AI';

                    let htmlBuilder = [];
                    const cl = data.content_learnings;

                    // ==================================================
                    // 1. EXECUTIVE HEADER & CONTENT LEARNINGS
                    // ==================================================
                    if (cl && cl.summary_header) {
                        htmlBuilder.push(`
                            <div class="report-header-card">
                                <h2 class="report-main-title">${cl.summary_header.title}</h2>
                                <span class="report-subtitle">${cl.summary_header.subtitle || 'Here’s what stood out from the Reels you shared.'}</span>
                                ${cl.summary_header.description ? `<p class="report-description">${cl.summary_header.description}</p>` : ''}
                            </div>
                        `);
                    }

                    // --------------------------------------------------
                    // 1. WHAT THESE REELS ARE ABOUT
                    // --------------------------------------------------
                    if (cl && Array.isArray(cl.what_these_reels_are_about) && cl.what_these_reels_are_about.length > 0) {
                        htmlBuilder.push(`
                            <div class="report-section">
                                <h3 class="section-title">1. WHAT THESE REELS ARE ABOUT</h3>
                                <div class="directions-container">
                        `);

                        cl.what_these_reels_are_about.forEach((cat) => {
                            htmlBuilder.push(`
                                <div class="direction-card">
                                    <div class="direction-card-header">
                                        <h4 class="direction-name">${cat.category_name}</h4>
                                    </div>
                                    <div class="direction-card-body">
                                        ${cat.summary_text ? `<p class="category-summary-text">${cat.summary_text}</p>` : ''}
                                        <ul class="direction-reels-list">
                            `);

                            if (Array.isArray(cat.reels)) {
                                cat.reels.forEach(r => {
                                    const titleStr = r.display_title || `Reel ${r.id}`;
                                    if (r.reel_url) {
                                        htmlBuilder.push(`<li>• <a href="${r.reel_url}" target="_blank" class="direction-reel-link">${titleStr} ↗</a></li>`);
                                    } else {
                                        htmlBuilder.push(`<li>• <span class="direction-reel-title">${titleStr}</span></li>`);
                                    }
                                });
                            }

                            htmlBuilder.push(`</ul>`);

                            if (cat.note) {
                                htmlBuilder.push(`
                                    <div class="direction-explanation why-separate">
                                        <p class="explanation-text">${cat.note}</p>
                                    </div>
                                `);
                            }

                            htmlBuilder.push(`</div></div>`);
                        });

                        htmlBuilder.push(`</div></div>`);
                    }

                    // --------------------------------------------------
                    // 2. WHAT STOOD OUT
                    // --------------------------------------------------
                    if (cl && Array.isArray(cl.what_stood_out) && cl.what_stood_out.length > 0) {
                        htmlBuilder.push(`
                            <div class="report-section">
                                <h3 class="section-title">2. WHAT STOOD OUT</h3>
                                <div class="learnings-grid">
                        `);

                        cl.what_stood_out.forEach((item) => {
                            htmlBuilder.push(`
                                <div class="learning-card">
                                    <div class="learning-card-header">
                                        <h4 class="learning-title">${item.title}</h4>
                                    </div>
                                    <div class="learning-card-body">
                                        <p class="block-text">${item.observation}</p>
                                    </div>
                                </div>
                            `);
                        });

                        htmlBuilder.push(`</div></div>`);
                    }

                    // --------------------------------------------------
                    // 3. WHAT YOU CAN TRY
                    // --------------------------------------------------
                    if (cl && Array.isArray(cl.what_you_can_try) && cl.what_you_can_try.length > 0) {
                        htmlBuilder.push(`
                            <div class="report-section">
                                <h3 class="section-title">3. WHAT YOU CAN TRY</h3>
                                <div class="experiments-grid">
                        `);

                        cl.what_you_can_try.forEach((exp) => {
                            const tryText = exp.what_to_try || exp.try || '';
                            const whyText = exp.why_it_may_be_worth_trying || exp.why || '';
                            const exampleText = exp.simple_example || (Array.isArray(exp.how) ? exp.how.join(', ') : '');

                            htmlBuilder.push(`
                                <div class="experiment-card">
                                    <div class="exp-header">
                                        <h4 class="exp-title">${exp.title}</h4>
                                    </div>
                                    <div class="exp-body">
                                        ${tryText ? `<div class="exp-row"><span class="exp-label">What to try:</span> <p class="exp-val">${tryText}</p></div>` : ''}
                                        ${whyText ? `<div class="exp-row"><span class="exp-label">Why it may be worth trying:</span> <p class="exp-val">${whyText}</p></div>` : ''}
                                        ${exampleText ? `<div class="exp-row"><span class="exp-label">Simple example:</span> <p class="exp-val bold-text">${exampleText}</p></div>` : ''}
                                    </div>
                                </div>
                            `);
                        });

                        htmlBuilder.push(`</div></div>`);
                    }

                    // --------------------------------------------------
                    // 4. WHAT WE DON'T KNOW YET
                    // --------------------------------------------------
                    if (cl && (cl.what_we_dont_know_yet || cl.what_we_cannot_conclude)) {
                        const dontKnowText = typeof cl.what_we_dont_know_yet === 'string' 
                            ? cl.what_we_dont_know_yet 
                            : (Array.isArray(cl.what_we_cannot_conclude) ? cl.what_we_cannot_conclude.join(' ') : 'We do not have enough historical performance metrics yet to claim these formats definitely outperform others.');

                        htmlBuilder.push(`
                            <div class="report-section">
                                <h3 class="section-title title-cannot">4. WHAT WE DON'T KNOW YET</h3>
                                <div class="limitations-card">
                                    <p class="dont-know-text">${dontKnowText}</p>
                                </div>
                            </div>
                        `);
                    }

                    // --------------------------------------------------
                    // 5. ONE SIMPLE TAKEAWAY
                    // --------------------------------------------------
                    if (cl && (cl.one_simple_takeaway || cl.one_takeaway)) {
                        const takeawayText = cl.one_simple_takeaway || cl.one_takeaway;
                        htmlBuilder.push(`
                            <div class="takeaway-card">
                                <div class="takeaway-badge">🎯 ONE SIMPLE TAKEAWAY</div>
                                <p class="takeaway-text">"${takeawayText}"</p>
                            </div>
                        `);
                    }

                    // ==================================================
                    // COLLAPSIBLE REEL ANALYSES
                    // ==================================================
                    htmlBuilder.push(`
                        <details class="evidence-accordion">
                            <summary class="accordion-summary">
                                <span>🔍 View Individual Reel Analyses</span>
                                <span class="accordion-arrow">▼</span>
                            </summary>
                            <div class="accordion-content">
                    `);

                    // Individual Breakdown Cards
                    if (Array.isArray(data.reels) && data.reels.length > 0) {
                        data.reels.forEach((reelItem, index) => {
                            const reelNum = index + 1;
                            const isSuccess = reelItem.success;
                            const ra = reelItem.analysis;
                            const sourceLabel = reelItem.reel_url ? `Link ↗` : (reelItem.filename || `Reel #${reelNum}`);

                            htmlBuilder.push(`
                                <div class="reel-individual-card">
                                    <div class="reel-card-header">
                                        <div class="reel-badge-group">
                                            <span class="reel-num-tag">Reel #${reelNum}</span>
                                            <span class="reel-meta-tag">${reelItem.duration_sec ? `${reelItem.duration_sec}s` : ''} ${reelItem.has_audio ? '🔊 Audio' : '🔇 Silent'}</span>
                                        </div>
                                        ${reelItem.reel_url ? `<a href="${reelItem.reel_url}" target="_blank" class="reel-url-link">${sourceLabel}</a>` : ''}
                                    </div>
                            `);

                            if (!isSuccess || !ra) {
                                htmlBuilder.push(`
                                    <div class="reel-card-body">
                                        <p class="error-text">⚠️ Analysis failed for this Reel: ${reelItem.error || 'Could not fetch video.'}</p>
                                    </div>
                                `);
                            } else {
                                htmlBuilder.push(`<div class="reel-card-body">`);
                                if (ra.summary) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">📌 Summary</span><p class="item-text">${ra.summary}</p></div>`);
                                if (ra.topic) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">🎯 Topic</span><p class="item-text">${ra.topic}</p></div>`);
                                if (ra.content_category) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">📁 Category</span><p class="item-text">${ra.content_category}</p></div>`);
                                if (ra.hook) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">🪝 Hook (${ra.hook_type || 'Visual'})</span><p class="item-text">${ra.hook}</p></div>`);
                                if (ra.target_audience) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">👥 Target Audience</span><p class="item-text">${ra.target_audience}</p></div>`);
                                if (ra.storytelling_format) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">🎬 Format & Style</span><p class="item-text">${ra.storytelling_format} ${ra.visual_style ? `(${ra.visual_style})` : ''}</p></div>`);
                                if (ra.emotional_trigger) htmlBuilder.push(`<div class="analysis-item"><span class="item-label">💡 Psychological Trigger</span><p class="item-text">${ra.emotional_trigger}</p></div>`);
                                if (Array.isArray(ra.observations) && ra.observations.length) {
                                    htmlBuilder.push(`<div class="analysis-item"><span class="item-label">👁️ Evidence Observations</span><ul class="item-list">${ra.observations.map(o => `<li>• ${o}</li>`).join('')}</ul></div>`);
                                }
                                htmlBuilder.push(`</div>`);
                            }
                            htmlBuilder.push(`</div>`);
                        });
                    }

                    htmlBuilder.push(`</div></details>`);

                    if (statusMessage) statusMessage.innerHTML = htmlBuilder.join('');

                    if (statusFooter && data.ai_analysis?.usage) {
                        const usage = data.ai_analysis.usage;
                        statusFooter.innerHTML = `🔢 ${usage.prompt_tokens} prompt + ${usage.completion_tokens} completion = <strong>${usage.total_tokens} total tokens</strong>`;
                    }
                } else {
                    if (statusBadge) statusBadge.textContent = '⚠ Analysis Error';
                    if (statusMessage) statusMessage.innerHTML = `<p class="analysis-line">${data.message || 'Unknown error.'}</p>`;
                }
            } catch (error) {
                console.error('[App] Upload Error:', error);
                alert(`Upload failed: ${error.message}. Make sure FastAPI is running on port 8000.`);
            } finally {
                if (btnSubmit) {
                    btnSubmit.classList.remove('loading');
                    btnSubmit.querySelector('.btn-text').textContent = activeTab === 'multi_url' ? 'Analyze Multiple Reels →' : 'Analyze Reel';
                }
            }
        }

        if (btnSubmit) {
            btnSubmit.addEventListener('click', handleAnalyze);
        }

        if (form) {
            form.addEventListener('submit', handleAnalyze);
        }

        // --- Chatbot Logic ---
        const chatForm = document.getElementById('chatForm');
        const chatInput = document.getElementById('chatInput');
        const chatLog = document.getElementById('chatLog');
        const chatChips = document.querySelectorAll('.chat-chip');
        const btnSendChat = document.getElementById('btnSendChat');

        function appendMessage(role, text) {
            const msgDiv = document.createElement('div');
            msgDiv.className = `chat-message ${role}`;
            msgDiv.textContent = text;
            chatLog.appendChild(msgDiv);
            chatLog.scrollTop = chatLog.scrollHeight;
        }

        async function submitChatMessage(messageText) {
            if (!messageText) return;
            
            appendMessage('user', messageText);
            chatInput.value = '';
            
            // disable UI while fetching
            chatInput.disabled = true;
            btnSendChat.disabled = true;
            btnSendChat.textContent = '...';

            try {
                const response = await fetch('http://localhost:8000/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: messageText,
                        reels_context: currentReelsContext,
                        report_context: currentReportContext
                    })
                });

                if (!response.ok) throw new Error('Chat request failed');
                
                const data = await response.json();
                if (data.status === 'success') {
                    appendMessage('assistant', data.reply);
                } else {
                    appendMessage('assistant', 'Sorry, I ran into an error getting your answer.');
                }
            } catch (err) {
                console.error('[CHAT] Error:', err);
                appendMessage('assistant', 'Sorry, could not connect to the chat service.');
            } finally {
                chatInput.disabled = false;
                btnSendChat.disabled = false;
                btnSendChat.textContent = 'Send';
                chatInput.focus();
            }
        }

        if (chatForm) {
            chatForm.addEventListener('submit', (e) => {
                e.preventDefault();
                submitChatMessage(chatInput.value.trim());
            });
        }

        if (chatChips) {
            chatChips.forEach(chip => {
                chip.addEventListener('click', () => {
                    submitChatMessage(chip.textContent);
                });
            });
        }

        console.log('[App] Init complete. Listeners bound to btnSubmit, form, and chatbot.');

    } catch (initError) {
        console.error('[App] INIT CRASH — listeners failed to attach:', initError);
    }
})();


