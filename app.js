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

            try {
                const response = await fetch(API_URL, { method: 'POST', body: formData });
                if (!response.ok) throw new Error(`Server returned status ${response.status}`);

                const data = await response.json();
                console.log('[App] API response:', data);

                const ai = data.ai_analysis;
                const statusBadge = document.getElementById('statusBadge');
                const statusModel = document.getElementById('statusModel');
                const statusFooter = document.getElementById('statusFooter');

                if (statusBanner) statusBanner.classList.remove('hidden');

                if (ai && ai.success) {
                    if (statusBadge) statusBadge.textContent = '✦ Analysis Complete';
                    if (statusModel) statusModel.textContent = ai.model || '';

                    let formattedHtml = '';
                    const a = ai.analysis;
                    if (data.batch_count) {
                        if (statusBadge) statusBadge.textContent = `✦ Parallel Analysis Complete (${data.batch_count} Reels)`;
                        const items = [];
                        const b = a;
                        if (b.batch_summary) items.push(`<p class="analysis-heading">🚀 Cross-Reel Intelligence Summary</p><p class="analysis-line">${b.batch_summary}</p>`);
                        if (Array.isArray(b.dominant_hook_patterns) && b.dominant_hook_patterns.length) {
                            items.push(`<p class="analysis-heading">🪝 Dominant Hook Patterns</p><ul class="analysis-line">${b.dominant_hook_patterns.map(h=>`<li>• ${h}</li>`).join('')}</ul>`);
                        }
                        if (b.target_audience_overlap) items.push(`<p class="analysis-heading">👥 Target Audience Overlap</p><p class="analysis-line">${b.target_audience_overlap}</p>`);
                        if (Array.isArray(b.top_content_strengths) && b.top_content_strengths.length) {
                            items.push(`<p class="analysis-heading">✅ Top Content Strengths</p><ul class="analysis-line">${b.top_content_strengths.map(s=>`<li>• ${s}</li>`).join('')}</ul>`);
                        }
                        if (Array.isArray(b.cross_reel_opportunities) && b.cross_reel_opportunities.length) {
                            items.push(`<p class="analysis-heading">💡 Cross-Reel Opportunities</p><ul class="analysis-line">${b.cross_reel_opportunities.map(o=>`<li>• ${o}</li>`).join('')}</ul>`);
                        }
                        if (b.recommended_creator_strategy) {
                            items.push(`<p class="analysis-heading">🎯 Recommended Creator Strategy</p><p class="analysis-line">${b.recommended_creator_strategy}</p>`);
                        }

                        if (Array.isArray(data.reels) && data.reels.length) {
                            items.push(`<p class="analysis-heading" style="margin-top: 16px;">🎬 Individual Reel Breakdowns</p>`);
                            data.reels.forEach((r, idx) => {
                                const ra = r.ai_analysis?.analysis;
                                const topic = typeof ra === 'object' ? (ra.topic || ra.summary) : 'Reel Analysis';
                                items.push(`<p class="analysis-line"><strong>#${idx+1} ${topic}</strong> — <a href="${r.reel_url}" target="_blank" style="color:#c084fc;">Link ↗</a></p>`);
                            });
                        }
                        formattedHtml = items.join('');
                    } else if (typeof a === 'object' && a !== null) {
                        const items = [];
                        if (a.summary) items.push(`<p class="analysis-heading">📌 Summary</p><p class="analysis-line">${a.summary}</p>`);
                        if (a.topic) items.push(`<p class="analysis-heading">🎯 Topic</p><p class="analysis-line">${a.topic}</p>`);
                        if (a.content_category) items.push(`<p class="analysis-heading">📁 Category</p><p class="analysis-line">${a.content_category}</p>`);
                        if (a.hook) items.push(`<p class="analysis-heading">🪝 Hook (${a.hook_type || 'Visual'})</p><p class="analysis-line">${a.hook}</p>`);
                        if (a.target_audience) items.push(`<p class="analysis-heading">👥 Target Audience</p><p class="analysis-line">${a.target_audience}</p>`);
                        if (a.storytelling_format) items.push(`<p class="analysis-heading">🎬 Format</p><p class="analysis-line">${a.storytelling_format}</p>`);
                        if (a.visual_style) items.push(`<p class="analysis-heading">🎨 Visual Style</p><p class="analysis-line">${a.visual_style}</p>`);
                        if (a.emotional_trigger) items.push(`<p class="analysis-heading">💡 Emotional Trigger</p><p class="analysis-line">${a.emotional_trigger}</p>`);
                        
                        if (a.engagement_potential) {
                            const ep = a.engagement_potential;
                            const level = typeof ep === 'object' ? ep.level : ep;
                            const reason = typeof ep === 'object' ? ep.reason : '';
                            items.push(`<p class="analysis-heading">⚡ Engagement Potential: <strong>${level}</strong></p><p class="analysis-line">${reason}</p>`);
                        }

                        if (Array.isArray(a.key_messages) && a.key_messages.length) {
                            items.push(`<p class="analysis-heading">🔑 Key Messages</p><ul class="analysis-line">${a.key_messages.map(m=>`<li>• ${m}</li>`).join('')}</ul>`);
                        }
                        if (Array.isArray(a.content_strengths) && a.content_strengths.length) {
                            items.push(`<p class="analysis-heading">✅ Strengths</p><ul class="analysis-line">${a.content_strengths.map(s=>`<li>• ${s}</li>`).join('')}</ul>`);
                        }
                        if (Array.isArray(a.content_weaknesses) && a.content_weaknesses.length) {
                            items.push(`<p class="analysis-heading">⚠️ Weaknesses</p><ul class="analysis-line">${a.content_weaknesses.map(w=>`<li>• ${w}</li>`).join('')}</ul>`);
                        }
                        if (Array.isArray(a.content_opportunities) && a.content_opportunities.length) {
                            items.push(`<p class="analysis-heading">🚀 Opportunities</p><ul class="analysis-line">${a.content_opportunities.map(o=>`<li>• ${o}</li>`).join('')}</ul>`);
                        }
                        if (a.recommended_content_angle) {
                            items.push(`<p class="analysis-heading">💡 Recommended Creator Angle</p><p class="analysis-line">${a.recommended_content_angle}</p>`);
                        }
                        formattedHtml = items.join('');
                    } else {
                        formattedHtml = (a || '')
                            .split('\n')
                            .map(line => {
                                line = line.trim();
                                if (!line) return '';
                                if (/^\d+\./.test(line)) return `<p class="analysis-heading">${line}</p>`;
                                return `<p class="analysis-line">${line}</p>`;
                            })
                            .join('');
                    }

                    if (statusMessage) statusMessage.innerHTML = formattedHtml;

                    if (statusFooter && ai.usage) {
                        statusFooter.innerHTML = `🔢 ${ai.usage.prompt_tokens} prompt + ${ai.usage.completion_tokens} completion = <strong>${ai.usage.total_tokens} tokens</strong>`;
                    }
                } else {
                    // AI call failed but upload succeeded
                    if (statusBadge) statusBadge.textContent = '⚠ Upload OK — AI Error';
                    if (statusMessage) statusMessage.innerHTML = `<p class="analysis-line">${ai?.error || 'Unknown AI error.'}</p>`;
                    if (statusFooter) statusFooter.innerHTML = `File saved at: <code>${data.data?.saved_path || 'server'}</code>`;
                }
            } catch (error) {
                console.error('[App] Upload Error:', error);
                alert(`Upload failed: ${error.message}. Make sure FastAPI is running on port 8000.`);
            } finally {
                if (btnSubmit) {
                    btnSubmit.classList.remove('loading');
                    btnSubmit.querySelector('.btn-text').textContent = 'Analyze Reel';
                }
            }
        }

        if (btnSubmit) {
            btnSubmit.addEventListener('click', handleAnalyze);
        }

        if (form) {
            form.addEventListener('submit', handleAnalyze);
        }

        console.log('[App] Init complete. Listeners bound to btnSubmit and form.');

    } catch (initError) {
        console.error('[App] INIT CRASH — listeners failed to attach:', initError);
    }
})();


