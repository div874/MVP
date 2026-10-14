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
                    const btnShareReelHook = document.getElementById('btnShareReelHook');
                    if (btnShareReelHook) btnShareReelHook.style.display = 'inline-block';
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

        // ==================================================
        // COMETCHAT REAL-TIME CREATOR COLLABORATION ENGINE
        // ==================================================
        const COMETCHAT_CONFIG = {
            appID: '1684866fb545df608',
            region: 'in',
            authKey: '167fda37b0657bc5e4251bc5837047b5d93552b9',
            groupGUID: 'reel_creators_hub',
            groupName: 'Reel Creators Collaboration'
        };

        const CHAT_USERS = [
            { uid: 'creator_1', name: 'Alex (Creator)', avatar: '🎬' },
            { uid: 'creator_2', name: 'Sam (Video Editor)', avatar: '✂️' }
        ];
        let currentUserIdx = 0;
        let loggedInCometUser = null;

        const chatForm = document.getElementById('chatForm');
        const chatInput = document.getElementById('chatInput');
        const chatLog = document.getElementById('chatLog');
        const chatChips = document.querySelectorAll('.chat-chip');
        const btnSendChat = document.getElementById('btnSendChat');
        const cometChatStatusPill = document.getElementById('cometChatStatusPill');
        const cometChatStatusText = document.getElementById('cometChatStatusText');
        const currentChatUserBadge = document.getElementById('currentChatUserBadge');
        const currentUserAvatar = document.getElementById('currentUserAvatar');
        const currentUserName = document.getElementById('currentUserName');
        const btnSwitchUser = document.getElementById('btnSwitchUser');
        const btnShareReelHook = document.getElementById('btnShareReelHook');
        const btnToggleFloatingChat = document.getElementById('btnToggleFloatingChat');
        const chatLoadingNotice = document.getElementById('chatLoadingNotice');

        function updateStatusUI(text, isLive = true) {
            if (cometChatStatusText) cometChatStatusText.textContent = text;
            if (cometChatStatusPill) {
                cometChatStatusPill.style.borderColor = isLive ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)';
            }
        }

        function updateUserBadgeUI() {
            const user = CHAT_USERS[currentUserIdx];
            if (currentUserName) currentUserName.textContent = user.name;
            if (currentUserAvatar) currentUserAvatar.textContent = user.avatar;
        }

        function appendCometChatMessage(msg, isExplicitSelf = null) {
            if (chatLoadingNotice) chatLoadingNotice.style.display = 'none';

            const sender = msg.getSender ? msg.getSender() : null;
            const senderUid = sender ? sender.getUid() : (msg.senderUid || (msg.getSenderId ? msg.getSenderId() : ''));
            const text = msg.getText ? msg.getText() : (msg.text || '');
            const sentAt = msg.getSentAt ? new Date(msg.getSentAt() * 1000) : new Date();
            const timeStr = sentAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            const currentUid = loggedInCometUser ? loggedInCometUser.getUid() : 'creator_1';
            const isUserSelf = isExplicitSelf !== null ? isExplicitSelf : (senderUid === currentUid);

            let displayName = 'Creator';
            let avatar = '🎬';
            if (senderUid === 'creator_2') {
                displayName = 'Sam (Video Editor)';
                avatar = '✂️';
            } else if (senderUid === 'creator_1') {
                displayName = 'Alex (Creator)';
                avatar = '🎬';
            } else if (sender) {
                displayName = sender.getName() || 'Reel Creator';
                avatar = isUserSelf ? '🎬' : '✂️';
            }

            const msgDiv = document.createElement('div');
            msgDiv.className = `chat-message ${isUserSelf ? 'self' : 'other'}`;

            let bubbleContent = escapeHtml(text);
            if (text.includes('[Shared Reel Analysis]')) {
                const parts = text.split('[Shared Reel Analysis]');
                bubbleContent = `
                    <div class="reel-analysis-card">
                        <div class="reel-card-badge">📊 Reel Intelligence Shared</div>
                        <div class="reel-card-body">${escapeHtml(parts[1] ? parts[1].trim() : text)}</div>
                    </div>
                `;
            }

            if (isUserSelf) {
                msgDiv.innerHTML = `
                    <div class="chat-content-wrap">
                        <div class="chat-meta">
                            <span class="chat-sender-name">${displayName}</span>
                            <span class="chat-time">${timeStr}</span>
                        </div>
                        <div class="chat-bubble">${bubbleContent}</div>
                    </div>
                    <div class="chat-msg-avatar" title="${displayName}">${avatar}</div>
                `;
            } else {
                msgDiv.innerHTML = `
                    <div class="chat-msg-avatar" title="${displayName}">${avatar}</div>
                    <div class="chat-content-wrap">
                        <div class="chat-meta">
                            <span class="chat-sender-name">${displayName}</span>
                            <span class="chat-time">${timeStr}</span>
                        </div>
                        <div class="chat-bubble">${bubbleContent}</div>
                    </div>
                `;
            }

            chatLog.appendChild(msgDiv);
            chatLog.scrollTop = chatLog.scrollHeight;
        }

        function escapeHtml(str) {
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        async function initCometChatLounge() {
            if (typeof CometChat === 'undefined') {
                console.warn('[CometChat] SDK not loaded yet. Retrying in 1s...');
                setTimeout(initCometChatLounge, 1000);
                return;
            }

            try {
                updateStatusUI('CometChat: Connecting...', false);
                const appSettings = new CometChat.AppSettingsBuilder()
                    .subscribePresenceForAllUsers()
                    .setRegion(COMETCHAT_CONFIG.region)
                    .autoEstablishSocketConnection(true)
                    .build();

                await CometChat.init(COMETCHAT_CONFIG.appID, appSettings);
                console.log('[CometChat] Init successful.');

                await loginOrRegisterUser(CHAT_USERS[currentUserIdx]);
                await joinOrCreateCollaborationGroup();
                await fetchRecentMessages();
                setupRealtimeListener();

                updateStatusUI('CometChat: Live (#reel-creators-lounge)', true);
            } catch (err) {
                console.error('[CometChat] Init/Setup error:', err);
                updateStatusUI('CometChat: Offline', false);
            }
        }

        async function loginOrRegisterUser(userObj) {
            try {
                const currentUser = await CometChat.getLoggedinUser();
                if (currentUser && currentUser.getUid() === userObj.uid) {
                    loggedInCometUser = currentUser;
                    console.log('[CometChat] Already logged in as:', currentUser.getName());
                    updateUserBadgeUI();
                    return currentUser;
                }

                if (currentUser) {
                    await CometChat.logout();
                }

                try {
                    loggedInCometUser = await CometChat.login(userObj.uid, COMETCHAT_CONFIG.authKey);
                } catch (loginErr) {
                    if (loginErr && loginErr.code === 'ERR_UID_NOT_FOUND') {
                        console.log(`[CometChat] User ${userObj.uid} not found, creating dynamically...`);
                        const newUser = new CometChat.User(userObj.uid);
                        newUser.setName(userObj.name);
                        await CometChat.createUser(newUser, COMETCHAT_CONFIG.authKey);
                        loggedInCometUser = await CometChat.login(userObj.uid, COMETCHAT_CONFIG.authKey);
                    } else {
                        throw loginErr;
                    }
                }

                console.log('[CometChat] Logged in successfully:', loggedInCometUser.getName());
                updateUserBadgeUI();
                return loggedInCometUser;
            } catch (err) {
                console.error('[CometChat] Login error:', err);
                throw err;
            }
        }

        async function joinOrCreateCollaborationGroup() {
            try {
                const GUID = COMETCHAT_CONFIG.groupGUID;
                const groupName = COMETCHAT_CONFIG.groupName;
                const groupType = CometChat.GROUP_TYPE.PUBLIC;

                try {
                    const group = new CometChat.Group(GUID, groupName, groupType, '');
                    await CometChat.createGroup(group);
                    console.log('[CometChat] Group created successfully.');
                } catch (grpErr) {
                    // Group already exists, attempt to join
                    try {
                        await CometChat.joinGroup(GUID, groupType, '');
                        console.log('[CometChat] Joined existing group.');
                    } catch (joinErr) {
                        // Already member or joined
                        console.log('[CometChat] Already a member of group.');
                    }
                }
            } catch (e) {
                console.error('[CometChat] Group handling error:', e);
            }
        }

        async function fetchRecentMessages() {
            try {
                chatLog.innerHTML = '';
                const messagesRequest = new CometChat.MessagesRequestBuilder()
                    .setGUID(COMETCHAT_CONFIG.groupGUID)
                    .setLimit(25)
                    .build();

                const messages = await messagesRequest.fetchPrevious();
                if (messages && messages.length > 0) {
                    messages.forEach(msg => {
                        if (msg.getText) appendCometChatMessage(msg);
                    });
                } else {
                    chatLog.innerHTML = `
                        <div class="chat-loading-notice">
                            <span>Welcome to the #reel-creators-lounge! Send the first message below. 🚀</span>
                        </div>
                    `;
                }
            } catch (err) {
                console.error('[CometChat] Fetch history error:', err);
            }
        }

        function setupRealtimeListener() {
            const listenerId = 'reel_collaboration_listener';
            CometChat.removeMessageListener(listenerId);

            CometChat.addMessageListener(
                listenerId,
                new CometChat.MessageListener({
                    onTextMessageReceived: (textMessage) => {
                        console.log('[CometChat] Real-time message received:', textMessage);
                        if (textMessage.getReceiverId() === COMETCHAT_CONFIG.groupGUID) {
                            appendCometChatMessage(textMessage, false);
                        }
                    }
                })
            );
            console.log('[CometChat] Real-time message listener active.');
        }

        async function sendCometChatMessage(text) {
            if (!text || !text.trim()) return;
            const messageText = text.trim();

            if (!loggedInCometUser) {
                alert('CometChat is still connecting. Please try again in a moment.');
                return;
            }

            if (chatInput) chatInput.value = '';
            if (btnSendChat) btnSendChat.disabled = true;

            try {
                const textMessage = new CometChat.TextMessage(
                    COMETCHAT_CONFIG.groupGUID,
                    messageText,
                    CometChat.RECEIVER_TYPE.GROUP
                );

                const sentMessage = await CometChat.sendMessage(textMessage);
                console.log('[CometChat] Message sent successfully:', sentMessage);
                appendCometChatMessage(sentMessage, true);
            } catch (err) {
                console.error('[CometChat] Send error:', err);
                alert('Could not send message over CometChat: ' + (err.message || 'Network error'));
            } finally {
                if (btnSendChat) btnSendChat.disabled = false;
                if (chatInput) {
                    chatInput.disabled = false;
                    chatInput.focus();
                }
            }
        }

        if (chatForm) {
            chatForm.addEventListener('submit', (e) => {
                e.preventDefault();
                sendCometChatMessage(chatInput.value);
            });
        }

        if (chatChips) {
            chatChips.forEach(chip => {
                chip.addEventListener('click', () => {
                    sendCometChatMessage(chip.textContent);
                });
            });
        }

        if (btnSwitchUser) {
            btnSwitchUser.addEventListener('click', async () => {
                btnSwitchUser.disabled = true;
                btnSwitchUser.textContent = 'Switching...';
                currentUserIdx = (currentUserIdx + 1) % CHAT_USERS.length;
                try {
                    await loginOrRegisterUser(CHAT_USERS[currentUserIdx]);
                    await fetchRecentMessages();
                } catch (e) {
                    console.error('Switch user error:', e);
                } finally {
                    btnSwitchUser.disabled = false;
                    btnSwitchUser.textContent = '🔄 Switch User';
                }
            });
        }

        if (btnShareReelHook) {
            btnShareReelHook.addEventListener('click', () => {
                const report = currentReportContext || {};
                let summaryTitle = report.summary_header?.title || 'Reel Analysis Complete';
                let topHook = report.takeaways?.[0] || 'Strong visual pattern interrupt detected in initial 2 seconds.';
                let shareText = `🎬 [Shared Reel Analysis] ${summaryTitle} — Hook Strategy: "${topHook}"`;
                sendCometChatMessage(shareText);
            });
        }

        if (btnToggleFloatingChat) {
            btnToggleFloatingChat.addEventListener('click', () => {
                const lounge = document.getElementById('chatSection');
                if (lounge) lounge.scrollIntoView({ behavior: 'smooth' });
                if (chatInput) setTimeout(() => chatInput.focus(), 400);
            });
        }

        // Initialize CometChat Lounge on page load
        initCometChatLounge();

        console.log('[App] Init complete. Listeners bound to btnSubmit, form, and CometChat lounge.');

    } catch (initError) {
        console.error('[App] INIT CRASH — listeners failed to attach:', initError);
    }
})();


