document.addEventListener('DOMContentLoaded', () => {
    // --- GLOBAL VARIABLES START ---
    // --- GLOBAL ERROR TRACKING ---
    window.onerror = function(message, source, lineno, colno, error) {
        const errorMsg = `Error: ${message} at ${source}:${lineno}:${colno}`;
        console.error(errorMsg);
        if (typeof log === 'function') {
            log(errorMsg, 'error');
        }
        return false;
    };

    console.log("Dashboard Script Initialized");
    const token = localStorage.getItem('token');

    // --- GUEST MODE LOGIC ---
    if (!token) {
        // Change UI for guest
        const creditsEl = document.getElementById('creditsDisplay');
        const statusEl = document.getElementById('systemStatusDisplay');
        const usernameEl = document.getElementById('sidebarUsername');

        if (creditsEl) {
            creditsEl.className = ''; // Remove status style
            creditsEl.innerHTML = '<a href="/login.html" class="primary-btn" style="text-decoration: none; padding: 6px 12px; font-size: 0.9rem;">Login</a>';
            creditsEl.style.background = 'none';
            creditsEl.style.border = 'none';
        }

        if (statusEl) {
            statusEl.className = '';
            statusEl.innerHTML = '<a href="/login.html?mode=register" style="text-decoration: none; padding: 6px 12px; font-size: 0.9rem; background: rgba(59,130,246,0.2); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); border-radius: 8px; margin-left: 8px;">Register</a>';
            statusEl.style.background = 'none';
        }

        if (usernameEl) {
            usernameEl.innerHTML = 'Guest';
        }

        const profileModalUsernameEl = document.getElementById('profileModalUsername');
        if (profileModalUsernameEl) {
            profileModalUsernameEl.textContent = 'Guest';
        }
    }

    // --- PAYMENT CONFIG START ---
    let cachedSquadPublicKey = null;
    async function fetchPaymentConfig() {
        if (!token) return;
        try {
            const configRes = await fetchWithAuth('/api/config/payment');
            if (configRes.ok) {
                const configData = await configRes.json();
                if (configData.squad_public_key) {
                    cachedSquadPublicKey = configData.squad_public_key;
                    console.log("Squad config loaded");
                }
            }
        } catch (e) {
            console.error("Failed to fetch payment config", e);
        }
    }
    // --- PAYMENT CONFIG END ---

    // --- PWA INSTALL LOGIC ---
    let deferredPrompt;
    const installBtn = document.getElementById('installAppBtn');

    window.addEventListener('beforeinstallprompt', (e) => {
        // Prevent Chrome 67 and earlier from automatically showing the prompt
        e.preventDefault();
        // Stash the event so it can be triggered later.
        deferredPrompt = e;
        // Update UI to notify the user they can add to home screen
        if (installBtn) installBtn.style.display = 'flex';
        console.log("PWA: capable of custom install prompt");
    });

    if (installBtn) {
        installBtn.addEventListener('click', (e) => {
            e.preventDefault();
            // Show the prompt
            if (deferredPrompt) {
                deferredPrompt.prompt();
                // Wait for the user to respond to the prompt
                deferredPrompt.userChoice.then((choiceResult) => {
                    if (choiceResult.outcome === 'accepted') {
                        console.log('User accepted the A2HS prompt');
                    } else {
                        console.log('User dismissed the A2HS prompt');
                    }
                    deferredPrompt = null;
                    installBtn.style.display = 'none';
                });
            }
        });
    }

    window.addEventListener('appinstalled', () => {
        console.log('PWA was installed');
        if (installBtn) installBtn.style.display = 'none';
    });

    // Auth Helper
    async function fetchWithAuth(url, options = {}) {
        if (!token) {
            console.warn("Guest mode: Skipping auth fetch to " + url);
            // Return a dummy response that mimics empty data or failure
            // This prevents the app from crashing when loading stats/history
            return {
                ok: false,
                status: 401,
                json: async () => [] // Returns empty array/object
            };
        }

        const headers = options.headers || {};
        headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(url, { ...options, headers });

        if (res.status === 401) {
            localStorage.removeItem('token');
            window.location.href = '/login.html';
            throw new Error('Unauthorized');
        }

        return res;
    }

    // Elements
    const urlInput = document.getElementById('urlInput');
    const startBatchBtn = document.getElementById('startBatchBtn');
    const stopBatchBtn = document.getElementById('stopBatchBtn');
    const toneSelect = document.getElementById('toneSelect');
    const consoleLog = document.getElementById('consoleLog');
    const reviewList = document.getElementById('reviewList');
    const queueCount = document.getElementById('queueCount');
    const todayCount = document.getElementById('todayCount');
    const clearConsoleBtn = document.getElementById('clearConsole');

    // State
    let isProcessing = false;
    let shouldStop = false;
    let chartInstance = null;
    let minLogIdToDisplay = parseInt(localStorage.getItem('minLogIdToDisplay')) || 0;
    let maxSeenLogId = 0; // Fix: Define maxSeenLogId
    const locallyDeletedIds = new Set(); // Fix: Define locallyDeletedIds

    // Sidebar Toggle
    const sidebarToggleBtn = document.getElementById('sidebarToggle');
    const sidebar = document.querySelector('.sidebar');

    // Add overlay for mobile
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);

    function toggleSidebar() {
        const isHidden = sidebar.classList.contains('hidden');
        if (isHidden) {
            sidebar.classList.remove('hidden');
            if (window.innerWidth <= 768) {
                overlay.classList.add('active');
            }
        } else {
            sidebar.classList.add('hidden');
            overlay.classList.remove('active');
        }
    }

    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', toggleSidebar);
    }

    overlay.addEventListener('click', () => {
        sidebar.classList.add('hidden');
        overlay.classList.remove('active');
    });

    // Check mobile on load
    if (window.innerWidth <= 768) {
        sidebar.classList.add('hidden');
    }

    // Initialize
    try {
        if (typeof Chart !== 'undefined') {
            initChart();
        } else {
            console.warn("Chart.js not loaded, skipping chart initialization");
        }
    } catch (e) {
        console.error("Failed to initialize chart:", e);
    }
    loadStats();
    loadQueue(); // Load persisted queue items
    loadCurrentUser();
    pollStatus(); // Start polling
    fetchPaymentConfig(); // Pre-fetch squad key
    setInterval(pollStatus, 5000); // Poll every 5 seconds

    // Event Listeners
    startBatchBtn.addEventListener('click', startBatchProcessing);
    stopBatchBtn.addEventListener('click', async () => {
        if (isProcessing) {
            try {
                await fetchWithAuth('/api/batch/stop', { method: 'POST' });
                stopBatchBtn.disabled = true;
                stopBatchBtn.textContent = 'Stopping...';
            } catch (e) {
                console.error('Failed to stop batch', e);
            }
        }
    });

    clearConsoleBtn.addEventListener('click', () => {
        // 1. Visually clear immediately
        consoleLog.innerHTML = '';

        // 2. Set the "minimum ID" to the highest ID we have seen so far
        if (maxSeenLogId > 0) {
            minLogIdToDisplay = maxSeenLogId;
            // 3. Save this to the browser so it remembers after refresh
            localStorage.setItem('minLogIdToDisplay', minLogIdToDisplay);
        }
    });


    // Navigation
    const navItems = document.querySelectorAll('.nav-item');
    const views = document.querySelectorAll('.view-section');
    const pageTitle = document.getElementById('pageTitle');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();

            // Update Nav
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            // Update View
            const targetId = item.dataset.view;
            views.forEach(view => {
                view.style.display = view.id === targetId ? 'block' : 'none';
            });

            // Update Title
            pageTitle.textContent = item.textContent.trim().split(' ')[1]; // Remove emoji

            // Mobile: Close sidebar on nav click
            if (window.innerWidth <= 768) {
                sidebar.classList.add('hidden');
                overlay.classList.remove('active');
            }

            // Load specific data if needed
            if (targetId === 'settings-view') {
                loadSettings();
            } else if (targetId === 'history-view') {
                loadHistory();
            } else if (targetId === 'referrals-view') {
                loadReferrals();
            } else if (targetId === 'admin-status-view') {
                if (typeof loadAdminStats === 'function') {
                    loadAdminStats();
                } else {
                    console.error("loadAdminStats is not defined");
                }
            }
        });
    });

    // Settings Buttons
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    const settingsLogoutBtn = document.getElementById('settingsLogoutBtn');
    const addScrapingAccountBtn = document.getElementById('addScrapingAccountBtn');

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveSettings);
    }

    if (settingsLogoutBtn) {
        settingsLogoutBtn.addEventListener('click', () => {
            localStorage.removeItem('token');
            window.location.href = '/login.html';
        });
    }

    if (addScrapingAccountBtn) {
        addScrapingAccountBtn.addEventListener('click', () => addScrapingAccount());
    }

    // Helper: Log to Console
    function log(message, type = 'info') {
        const div = document.createElement('div');
        div.className = `log-entry ${type}`;
        div.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        consoleLog.appendChild(div);
        consoleLog.scrollTop = consoleLog.scrollHeight;
    }

    // Load Queue from Backend (Smart Diffing Version)
    async function loadQueue() {
        try {
            const res = await fetchWithAuth('/api/queue');
            const queueItems = await res.json();

            // DEBUG: Print what we got from the server
            console.log("Queue items from server:", queueItems);

            // 1. Get IDs that are currently in the DB
            const backendIds = new Set(queueItems.map(item => item.id));

            // 2. Clean up our "Ignore List"
            if (typeof locallyDeletedIds !== 'undefined') {
                locallyDeletedIds.forEach(id => {
                    if (!backendIds.has(id)) locallyDeletedIds.delete(id);
                });
            }

            // 3. Remove items from DOM
            const currentDomItems = Array.from(reviewList.querySelectorAll('.review-item'));
            currentDomItems.forEach(el => {
                const qId = parseInt(el.dataset.queueId);
                // Safety check: ensure locallyDeletedIds exists before checking it
                const isIgnored = (typeof locallyDeletedIds !== 'undefined') && locallyDeletedIds.has(qId);

                if (qId && (!backendIds.has(qId) || isIgnored)) {
                    console.log("Removing item:", qId);
                    el.remove();
                }
            });

            // 4. Add new items
            queueItems.forEach(item => {
                const isIgnored = (typeof locallyDeletedIds !== 'undefined') && locallyDeletedIds.has(item.id);
                if (isIgnored) return;

                const exists = reviewList.querySelector(`.review-item[data-queue-id="${item.id}"]`);
                if (!exists) {
                    console.log("Adding item to DOM:", item.id);
                    addToReviewQueue(item.tweet_id, item.tweet_text, item.reply_text, item.id);
                }
            });

            updateQueueCount();

        } catch (e) {
            console.error('CRITICAL JS ERROR in loadQueue:', e);
        }
    }

    // Polling for status and logs
    // Polling for status and logs
    async function pollStatus() {
        try {
            // Updated to use the unified summary endpoint
            const summaryRes = await fetchWithAuth('/api/dashboard/summary');
            if (!summaryRes.ok) return;
            
            const summary = await summaryRes.json();
            
            // 1. Update Batch Status
            const status = summary.batch;
            if (status.is_processing) {
                isProcessing = true;
                startBatchBtn.style.display = 'none';
                stopBatchBtn.style.display = 'inline-block';
                stopBatchBtn.disabled = false;
                stopBatchBtn.textContent = 'Stop';
            } else {
                isProcessing = false;
                startBatchBtn.style.display = 'inline-block';
                stopBatchBtn.style.display = 'none';
                startBatchBtn.disabled = false;
            }

            // 2. Update Logs
            const logs = summary.logs;
            const newLogs = logs.filter(log => log.id > maxSeenLogId);

            if (newLogs.length > 0) {
                newLogs.forEach(log => {
                    if (log.id > maxSeenLogId) {
                        maxSeenLogId = log.id;
                    }
                    if (log.id > minLogIdToDisplay) {
                        const div = document.createElement('div');
                        div.className = `log-entry ${log.level.toLowerCase()}`;
                        div.textContent = `[${log.timestamp}] ${log.message}`;
                        consoleLog.appendChild(div);
                    }
                });
                consoleLog.scrollTop = consoleLog.scrollHeight;
            }

            // 3. Update Queue
            const queueItems = summary.queue;
            const backendIds = new Set(queueItems.map(item => item.id));

            if (typeof locallyDeletedIds !== 'undefined') {
                locallyDeletedIds.forEach(id => {
                    if (!backendIds.has(id)) locallyDeletedIds.delete(id);
                });
            }

            const currentDomItems = Array.from(reviewList.querySelectorAll('.review-item'));
            currentDomItems.forEach(el => {
                const qId = parseInt(el.dataset.queueId);
                const isIgnored = (typeof locallyDeletedIds !== 'undefined') && locallyDeletedIds.has(qId);
                if (qId && (!backendIds.has(qId) || isIgnored)) {
                    el.remove();
                }
            });

            queueItems.forEach(item => {
                const isIgnored = (typeof locallyDeletedIds !== 'undefined') && locallyDeletedIds.has(item.id);
                if (isIgnored) return;
                const exists = reviewList.querySelector(`.review-item[data-queue-id="${item.id}"]`);
                if (!exists) {
                    addToReviewQueue(item.tweet_id, item.tweet_text, item.reply_text, item.id);
                }
            });
            updateQueueCount();

            // 4. Update Credits (Header)
            if (summary.credits !== undefined) {
                const creditsEl = document.getElementById('creditsDisplay');
                if (creditsEl) {
                    creditsEl.textContent = `Credits: ${summary.credits}`;
                }
            }

        } catch (e) {
            console.error('Unified polling error:', e);
        }
    }

    async function startBatchProcessing() {
        if (!token) {
            window.location.href = '/login.html';
            return;
        }

        if (isProcessing) return;

        // Remember original state
        const originalText = startBatchBtn.textContent;
        // Give immediate visual feedback that the button was clicked
        startBatchBtn.textContent = 'Processing...';
        startBatchBtn.disabled = true;

        const rawText = urlInput.value;
        const urlRegex = /(?:https?:\/\/)?(?:www\.)?(?:x|twitter)\.com\/(?:[a-zA-Z0-9_]+\/status\/[0-9]+|intent\/(?:tweet|like)\?[^\s]+)/g;
        const urls = rawText.match(urlRegex) || [];

        // Also allow raw IDs on separate lines
        const rawIds = rawText.split('\n').map(l => l.trim()).filter(l => /^\d{15,20}$/.test(l));
        urls.push(...rawIds);

        if (urls.length === 0) {
            log('No valid X/Twitter URLs or IDs found.', 'error');
            alert('No valid X/Twitter URLs or Tweet IDs found in the input.');
            startBatchBtn.textContent = originalText;
            startBatchBtn.disabled = false;
            return;
        }

        // Update input with cleaned URLs
        urlInput.value = urls.join('\n');

        try {
            // First attempt - assuming no payment proof yet
            let res = await fetchWithAuth('/api/batch/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls, tone: toneSelect.value })
            });

            if (res.status === 402) {
                // Payment Required!
                log('💰 Payment required to start this Raid...', 'warning');

                if (!window.ethereum) {
                    alert("Metamask/Web3 wallet is required for payment!");
                    return;
                }

                // Get payment details from headers
                const recipient = res.headers.get('x402-recipient') || '0x0000000000000000000000000000000000000000';
                const price = res.headers.get('x402-price');
                const token = res.headers.get('x402-token');
                const chain = res.headers.get('x402-chain');

                // Request account access
                const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
                const account = accounts[0];

                // Switch to Base Sepolia (84532)
                try {
                    await window.ethereum.request({
                        method: 'wallet_switchEthereumChain',
                        params: [{ chainId: '0x14a34' }], // 84532 in hex
                    });
                } catch (switchError) {
                    // This error code indicates that the chain has not been added to MetaMask.
                    if (switchError.code === 4902) {
                        alert("Please add Base Sepolia to your wallet!");
                        return;
                    }
                }

                log('Initiating payment of 0.0001 ETH...', 'info');

                // Send Transaction (Simple Send for testing)
                // In production, you might interact with a contract
                // Here we send to a null address or the facilitator's address if known
                // For x402-open, the facilitator validates the payload, which usually includes the txHash
                // We'll send to a burn/test address for now, or you can update this to your address
                const txHash = await window.ethereum.request({
                    method: 'eth_sendTransaction',
                    params: [
                        {
                            from: account,
                            to: recipient,
                            value: '0x5Af3107A4000', // 0.0001 ETH (100000000000000 wei)
                            chainId: '0x14a34'
                        },
                    ],
                });

                log(`Payment sent! Tx: ${txHash}`, 'success');
                log('Verifying payment with facilitator...', 'info');

                // Retry with structured proof
                // Map chain ID to slug
                const networkSlug = chain === '84532' ? 'base-sepolia' : 'base-sepolia';

                res = await fetchWithAuth('/api/batch/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        urls,
                        tone: toneSelect.value,
                        payment_proof: {
                            paymentPayload: {
                                x402Version: 1,
                                scheme: 'exact',
                                network: networkSlug,
                                authorization: {
                                    from: account
                                },
                                payload: {
                                    transaction: txHash,
                                    rpcUrl: "https://base-sepolia.g.alchemy.com/v2/dgYKsy3XMSSP5x7-L9hBx"
                                }
                            },
                            paymentRequirements: {
                                scheme: 'exact',
                                maxAmountRequired: price,
                                asset: token,
                                from: account,
                                payTo: recipient,
                                network: networkSlug,
                                description: "Batch Processing Fee",
                                resource: "http://localhost:8000/api/batch/start",
                                mimeType: "application/json",
                                maxTimeoutSeconds: 3600
                            }
                        }
                    })
                });
            }

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to start batch');
            }

            log(`Started batch processing for ${urls.length} URLs`, 'success');

        } catch (e) {
            log(`Error starting batch: ${e.message}`, 'error');
            alert(`Error starting batch: ${e.message}`);
        } finally {
            if (!isProcessing) {
                // Only reset if we haven't officially entered "processing" state according to pollStatus
                startBatchBtn.textContent = originalText;
                startBatchBtn.disabled = false;
            }
        }
    }

    function addToReviewQueue(tweetId, tweetText, replyText, queueId = null) {
        // Remove empty state if exists
        const empty = reviewList.querySelector('.empty-state');
        if (empty) empty.remove();

        const item = document.createElement('div');
        item.className = 'review-item';
        item.dataset.queueId = queueId || '';
        item.dataset.tweetText = tweetText || ''; // Store tweet text

        // Structure: We rely on [contenteditable="true"] to identify the text box
        item.innerHTML = `
                <div class="review-header">
                <span>ID: ${tweetId}</span>
                <span>${new Date().toLocaleTimeString()}</span>
            </div>
            <div class="review-text" style="color: #94a3b8; font-size: 0.85rem;">"${tweetText.substring(0, 100)}..."</div>
            <div class="review-text" contenteditable="true" style="white-space: pre-wrap;">${replyText}</div>
            <div class="review-actions">
                <div class="action-group">
                    <button class="btn-sm btn-secondary btn-copy" title="Copy to Clipboard">Copy</button>
                    <button class="btn-sm btn-secondary btn-intent" title="Open in X">Open</button>
                    <button class="btn-sm btn-secondary btn-done" title="Mark as Done">Done</button>
                </div>
                <div class="action-group">
                    <button class="btn-sm btn-discard">Discard</button>
                </div>
            </div>
                `;

        // Bind events
        const discardBtn = item.querySelector('.btn-discard');
        const copyBtn = item.querySelector('.btn-copy');
        const intentBtn = item.querySelector('.btn-intent');
        const doneBtn = item.querySelector('.btn-done');

        // --- FAIL-SAFE TEXT READER ---
        // This looks specifically for the attribute 'contenteditable="true"'
        const getCurrentText = () => {
            const textBox = item.querySelector('[contenteditable="true"]');
            if (!textBox) {
                console.error("CRITICAL: Could not find text box for item", tweetId);
                return "";
            }
            // Use innerText to preserve newlines, fallback to textContent
            return textBox.innerText || textBox.textContent || "";
        };

        // 2. Discard
        discardBtn.addEventListener('click', async () => {
            if (item.dataset.queueId && typeof locallyDeletedIds !== 'undefined') {
                locallyDeletedIds.add(parseInt(item.dataset.queueId));
            }

            if (item.dataset.queueId) {
                try {
                    await fetchWithAuth(`/api/queue/${item.dataset.queueId}`, { method: 'DELETE' });
                } catch (e) {
                    console.error('Failed to remove from queue', e);
                }
            }
            item.remove();
            updateQueueCount();
        });

        // 3. Copy
        copyBtn.addEventListener('click', () => {
            const textToCopy = getCurrentText();
            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalText = copyBtn.textContent;
                copyBtn.textContent = 'Done';
                setTimeout(() => copyBtn.textContent = originalText, 2000);
            });
        });

        // 4. Intent
        intentBtn.addEventListener('click', () => {
            showIntentModal(tweetId, getCurrentText(), item);
        });

        // 5. Done
        doneBtn.addEventListener('click', () => {
            const text = getCurrentText();
            console.log("Marking done with text:", text); // Debug Log

            if (!text.trim()) {
                alert("Cannot mark empty reply as done!");
                return;
            }
            markAsDone(item, tweetId, text);
        });

        reviewList.prepend(item);
        updateQueueCount();

        // Persist new items
        if (!queueId) {
            persistToQueue(tweetId, tweetText, replyText, item);
        }
    }

    async function persistToQueue(tweetId, tweetText, replyText, itemElement) {
        try {
            const response = await fetchWithAuth('/api/queue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tweet_id: tweetId, tweet_text: tweetText, reply_text: replyText })
            });

            if (!response.ok) throw new Error('Failed to persist to queue');

            const data = await response.json();
            // Store the queue ID in the element for later deletion
            itemElement.dataset.queueId = data.queue_id;
            // Update the reply ID to match queue ID if needed, but we used tweetId as fallback
            log(`Added to persistent queue`, 'success');
        } catch (error) {
            console.error('Failed to persist queue item', error);
            log(`Warning: Queue item not saved to database`, 'warning');
        }
    }

    async function markAsDone(itemElement, tweetId, replyText) {
        try {
            console.log("Marking as done:", tweetId); // Debug Log

            // 1. Add to Ignore List IMMEDIATELY
            // Use optional chaining (?.) just in case itemElement is null
            const queueId = itemElement?.dataset?.queueId ? parseInt(itemElement.dataset.queueId) : null;
            const tweetText = itemElement?.dataset?.tweetText || null;

            if (queueId && typeof locallyDeletedIds !== 'undefined') {
                locallyDeletedIds.add(queueId);
            }

            // 2. Visual Removal
            if (itemElement) itemElement.remove();

            // Also try to remove any duplicates by ID (just in case)
            if (queueId) {
                const dupe = document.querySelector(`.review-item[data-queue-id="${queueId}"]`);
                if (dupe) dupe.remove();
            }

            updateQueueCount();

            // 3. API Calls
            const response = await fetchWithAuth('/api/mark_done', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reply_text: replyText,
                    reply_to_id: tweetId,
                    tweet_text: tweetText
                })
            });

            if (!response.ok) throw new Error('Failed to mark as done API');

            if (queueId) {
                // Silently try to delete from queue DB
                fetchWithAuth(`/api/queue/${queueId}`, { method: 'DELETE' }).catch(err => console.log("Queue delete skipped", err));
            }

            log(`Marked reply to ${tweetId} as done`, 'success');
            loadStats();

        } catch (error) {
            console.error("markAsDone Error:", error);
            log(`Error: ${error.message} `, 'error');
            // If it failed, un-ignore so it comes back on next poll
            const queueId = itemElement?.dataset?.queueId ? parseInt(itemElement.dataset.queueId) : null;
            if (queueId && typeof locallyDeletedIds !== 'undefined') {
                locallyDeletedIds.delete(queueId);
            }
            loadQueue();
        }
    }




    // --- DEV FEATURE MODAL ---
    const devFeatureModal = document.getElementById('devFeatureModal');
    const devFeatureModalClose = document.getElementById('devFeatureModalClose');
    const devFeatureModalOk = document.getElementById('devFeatureModalOk');

    function showDevFeatureModal() {
        if (devFeatureModal) devFeatureModal.style.display = 'block';
    }

    if (devFeatureModalClose) {
        devFeatureModalClose.onclick = () => devFeatureModal.style.display = 'none';
    }
    if (devFeatureModalOk) {
        devFeatureModalOk.onclick = () => devFeatureModal.style.display = 'none';
    }

    // Close on click outside
    window.addEventListener('click', (event) => {
        if (event.target === devFeatureModal) {
            devFeatureModal.style.display = 'none';
        }
    });

    function updateQueueCount() {
        const count = reviewList.querySelectorAll('.review-item').length;
        queueCount.textContent = count;
        if (count === 0 && !reviewList.querySelector('.empty-state')) {
            reviewList.innerHTML = '<div class="empty-state">No replies pending review</div>';
        }
    }


    async function loadCurrentUser() {
        try {
            const res = await fetchWithAuth('/api/auth/me');
            if (res.ok) {
                const user = await res.json();
                const usernameEl = document.getElementById('sidebarUsername');
                if (usernameEl) {
                    usernameEl.innerHTML = `${user.username} `;
                }

                const profileModalUsernameEl = document.getElementById('profileModalUsername');
                if (profileModalUsernameEl) {
                    profileModalUsernameEl.textContent = user.username;
                }

                // Update Credits
                const creditsEl = document.getElementById('creditsDisplay');
                if (creditsEl) {
                    creditsEl.textContent = `Credits: ${user.credits !== undefined ? user.credits : 0}`;
                }

                // Admin Check
                // Admin Check
                console.log("Current user:", user.username);
                if (user.username && user.username.toLowerCase() === 'web3kaiju') {
                    const statusLink = document.getElementById('adminStatusLink');
                    if (statusLink) {
                        statusLink.style.display = 'flex'; // Changed to flex to match nav items
                        console.log("Admin Panel Activated");
                    }
                }
            }
        } catch (e) {
            console.error('Failed to load user info', e);
        }
    }

    // --- PAYMENT SUCCESS MODAL ---
    const paymentSuccessModal = document.getElementById('paymentSuccessModal');
    const successModalCredits = document.getElementById('successModalCredits');
    const successModalOk = document.getElementById('successModalOk');

    function showPaymentSuccessModal(credits) {
        if (paymentSuccessModal && successModalCredits) {
            successModalCredits.textContent = `+${credits} credits`;
            paymentSuccessModal.classList.add('active');
        } else {
            alert(`Payment successful! Added ${credits} credits.`);
        }
    }

    if (successModalOk) {
        successModalOk.onclick = () => paymentSuccessModal.classList.remove('active');
    }

    async function loadStats() {
        try {
            const res = await fetchWithAuth('/api/stats');
            const data = await res.json();

            // Update Success Rate
            const successRateEl = document.querySelector('.stat-card:nth-child(2) .stat-value');
            if (successRateEl) {
                successRateEl.textContent = `${data.success_rate}% `;
            }

            // Update Today's Count
            const stats = data.daily;
            if (stats.length > 0) {
                const today = new Date().toISOString().split('T')[0];
                const lastEntry = stats[stats.length - 1];
                if (lastEntry.date === today) {
                    todayCount.textContent = lastEntry.count;
                }
            }

            updateChart(stats);
        } catch (e) {
            if (token) console.error('Failed to load stats', e);
        }
    }

    // --- REFERRALS SYSTEM ---
    async function loadReferrals() {
        try {
            const res = await fetchWithAuth('/api/user/referrals');
            const data = await res.json();

            // Set referral link
            const baseUrl = window.location.origin;
            const refLink = `${baseUrl}/login.html?ref=${data.referral_code}`;
            document.getElementById('referralLinkInput').value = refLink;

            // Render list
            const tbody = document.getElementById('referralsListBody');
            const totalCountEl = document.getElementById('totalReferralsCount'); // New
            if (totalCountEl) {
                totalCountEl.textContent = data.referrals ? data.referrals.length : 0;
            }
            tbody.innerHTML = '';

            if (data.referrals && data.referrals.length > 0) {
                data.referrals.forEach(ref => {
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                    const localDate = new Date(ref.created_at + 'Z').toLocaleString();
                    tr.innerHTML = `
                        <td style="padding: 12px; font-weight: 500;">${ref.username}</td>
                        <td style="padding: 12px; text-align: right; color: #94a3b8; font-size: 0.9rem;">${localDate}</td>
                    `;
                    tbody.appendChild(tr);
                });
            } else {
                tbody.innerHTML = '<tr><td colspan="2" style="text-align: center; padding: 12px; color: #94a3b8;">No referrals yet. Share your link to earn more credits!</td></tr>';
            }
        } catch (e) {
            console.error('Failed to load referrals', e);
        }
    }

    const copyRefBtn = document.getElementById('copyReferralLinkBtn');
    if (copyRefBtn) {
        copyRefBtn.addEventListener('click', () => {
            const linkInput = document.getElementById('referralLinkInput');
            linkInput.select();
            document.execCommand("copy");
            const ogText = copyRefBtn.textContent;
            copyRefBtn.textContent = 'Copied!';
            setTimeout(() => { copyRefBtn.textContent = ogText; }, 2000);
        });
    }

    const refreshReferralsBtn = document.getElementById('refreshReferrals');
    if (refreshReferralsBtn) refreshReferralsBtn.addEventListener('click', loadReferrals);

    // --- SQUAD INTEGRATION ---
    const squadBtn = document.getElementById('squadCheckoutBtn');
    const customSquadBtn = document.getElementById('customSquadBtn');
    const customCreditsInput = document.getElementById('customCreditsInput');
    const customNgnDisplay = document.getElementById('customNgnDisplay');

    // Handle Custom Amount Input Change
    if (customCreditsInput && customNgnDisplay) {
        const updateNgn = () => {
            let credits = parseInt(customCreditsInput.value);
            if (isNaN(credits) || credits < 300) {
                customNgnDisplay.textContent = '₦-- NGN (Min 300)';
                return;
            }
            let ngn = Math.ceil(credits / 3);
            customNgnDisplay.textContent = `₦${ngn} NGN`;
        };

        customCreditsInput.addEventListener('input', updateNgn);

        const incBtn = document.getElementById('incrementCredits');
        const decBtn = document.getElementById('decrementCredits');

        if (incBtn) {
            incBtn.addEventListener('click', () => {
                let val = parseInt(customCreditsInput.value) || 300;
                customCreditsInput.value = val + 5;
                updateNgn();
            });
        }
        if (decBtn) {
            decBtn.addEventListener('click', () => {
                let val = parseInt(customCreditsInput.value) || 300;
                if (val > 300) {
                    customCreditsInput.value = Math.max(300, val - 5);
                    updateNgn();
                }
            });
        }
    }

    async function initiateSquadCheckout(amountNgn, creditsToAdd) {
        console.log("initiateSquadCheckout called with:", { amountNgn, creditsToAdd });
        if (!token) {
            alert("Please login first to purchase credits");
            return;
        }

        const usernameEl = document.getElementById('profileModalUsername');
        const displayUsername = usernameEl ? usernameEl.textContent : 'user';
        const cleanUsername = displayUsername.split('(')[0].trim().replace(/[^a-zA-Z0-9]/g, '');
        const userEmail = 'mumunihabib10@gmail.com';
        
        const referenceId = `sq_chk_${amountNgn}_` + Math.random().toString(36).substring(2, 15) + Date.now();

        console.log(`Initiating Squad: Amount=${amountNgn}, Credits=${creditsToAdd}, Email=${userEmail}, Ref=${referenceId}`);

        if (typeof squad === 'undefined' && typeof SquadPay === 'undefined') {
            console.error("Squad SDK is undefined! Check if checkout.squadco.com/widget/squad.min.js is loaded.");
            log("Critical Error: Squad SDK not loaded.", "error");
            alert("Error: Squad script not loaded. Please check your connection or disable ad-blockers.");
            return;
        }

        let publicKey = cachedSquadPublicKey;
        console.log("Current cachedSquadPublicKey:", publicKey);
        
        if (!publicKey || publicKey === 'pk_test_placeholder') {
             console.log("Key missing or placeholder, attempting to fetch...");
             await fetchPaymentConfig();
             publicKey = cachedSquadPublicKey;
        }

        if (!publicKey) {
             console.error("No Squad Public Key available even after fetch attempt.");
             alert("Configuration error: Squad Public Key not found. Please contact admin.");
             return;
        }

        try {
            console.log("Calling Squad setup...");
            const squadInstance = new squad({
                onClose: () => {
                    console.log('Squad Window closed');
                    log("Squad checkout closed by user.", "warning");
                },
                onLoad: () => {
                    console.log("Squad loaded successfully");
                },
                onSuccess: function(response) {
                    console.log("Squad Success Response:", response);
                    
                    log(`Payment authorized. Verifying reference: ${referenceId}...`, "INFO");

                    (async () => {
                        try {
                            const verificationRes = await fetchWithAuth('/api/payment/verify', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ reference: referenceId })
                            });

                            if (verificationRes.ok) {
                                const resData = await verificationRes.json();
                                showPaymentSuccessModal(resData.credits_added);
                                // Instant UI refresh
                                loadCurrentUser(); 
                                pollStatus(); 
                            } else {
                                const err = await verificationRes.json();
                                alert(`Payment verification failed: ${err.detail || 'Unknown error'}`);
                            }
                        } catch (vErr) {
                            console.error("Verification Network Error:", vErr);
                            alert("Network error during payment verification. Please contact support with your reference: " + referenceId);
                        }
                    })();
                },
                key: publicKey,
                email: userEmail,
                amount: amountNgn * 100, // NGN in kobo
                currency_code: 'NGN',
                transaction_ref: referenceId,
                payment_channels: ['card', 'bank', 'ussd', 'transfer']
            });
            console.log("Handler setup complete, calling setup/open...");
            squadInstance.setup();
            squadInstance.open();
        } catch (setupErr) {
            console.error("Squad Setup Crash:", setupErr);
            alert("Failed to initialize Squad: " + setupErr.message);
        }
    }

    if (squadBtn) {
        squadBtn.addEventListener('click', async () => {
            console.log("Squad 4000 Button Clicked");
            const originalText = squadBtn.textContent;
            squadBtn.textContent = 'Opening Squad...';
            squadBtn.disabled = true;
            try {
                await initiateSquadCheckout(4000, 15000); // Pro Package: 4k NGN for 15k credits
            } finally {
                squadBtn.textContent = originalText;
                squadBtn.disabled = false;
            }
        });
    }

    if (customSquadBtn) {
        customSquadBtn.addEventListener('click', async () => {
            let credits = parseInt(customCreditsInput.value);
            if (isNaN(credits) || credits < 300) {
                alert("Minimum purchase is 300 credits (₦100).");
                return;
            }
            let amountNgn = Math.ceil(credits / 3);
            
            const originalText = customSquadBtn.textContent;
            customSquadBtn.textContent = 'Opening...';
            customSquadBtn.disabled = true;
            try {
                await initiateSquadCheckout(amountNgn, credits);
            } finally {
                customSquadBtn.textContent = originalText;
                customSquadBtn.disabled = false;
            }
        });
    }

    function initChart() {
        const ctx = document.getElementById('activityChart').getContext('2d');
        chartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Replies',
                    data: [],
                    backgroundColor: '#3b82f6',
                    borderRadius: 4,
                    barThickness: 20
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#94a3b8' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8' }
                    }
                }
            }
        });
    }

    function updateChart(stats) {
        if (!chartInstance) return;

        const labels = [];
        const data = [];
        const today = new Date();

        for (let i = 6; i >= 0; i--) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            const dateStr = d.toISOString().split('T')[0];
            labels.push(dateStr.slice(5));

            const stat = stats.find(s => s.date === dateStr);
            data.push(stat ? stat.count : 0);
        }

        chartInstance.data.labels = labels;
        chartInstance.data.datasets[0].data = data;
        chartInstance.update();
    }

    // Modal Handling
    const modal = document.getElementById('intentModal');
const modalTweetId = document.getElementById('modalTweetId');
const modalComment = document.getElementById('modalComment');
const modalConfirm = document.getElementById('modalConfirm');
const modalCancel = document.getElementById('modalCancel');
const modalClose = document.querySelector('.modal-close');

let pendingIntentUrl = null;
let pendingItemElement = null;
let pendingTweetId = null;
let pendingReplyText = null;

function showIntentModal(tweetId, comment, itemElement) {
    try {
        log('Opening intent modal...', 'info');
        if (modalTweetId) modalTweetId.textContent = tweetId;
        if (modalComment) modalComment.textContent = comment;

        pendingIntentUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(comment)}&in_reply_to=${tweetId}`;
        pendingItemElement = itemElement;
        pendingTweetId = tweetId;
        pendingReplyText = comment;

        // Immediately open Twitter in new tab
        try {
            window.open(pendingIntentUrl, '_blank');
        } catch (err) {
            console.error('Failed to open Twitter window:', err);
            log('Popup blocked? Please allow popups.', 'warning');
        }

        // Show the modal for confirmation when user returns
        if (modal) {
            modal.classList.add('active');
            log('Modal activated', 'success');
        } else {
            console.error('Modal element not found');
        }
    } catch (e) {
        console.error('Error in showIntentModal:', e);
        log(`Error showing modal: ${e.message}`, 'error');
    }
}

function hideIntentModal() {
    modal.classList.remove('active');
    pendingIntentUrl = null;
    pendingItemElement = null;
    pendingTweetId = null;
    pendingReplyText = null;
}

if (modalConfirm) {
    modalConfirm.addEventListener('click', async () => {
        console.log("Modal Confirm Clicked"); // Debug Log

        // Check if we have the pending data
        if (pendingTweetId && pendingReplyText) {
            // Pass the stored element (pendingItemElement) to markAsDone
            await markAsDone(pendingItemElement, pendingTweetId, pendingReplyText);
            hideIntentModal();
        } else {
            console.error("Missing pending data for modal confirm");
            hideIntentModal();
        }
    });
}

if (modalCancel) modalCancel.addEventListener('click', hideIntentModal);
if (modalClose) modalClose.addEventListener('click', hideIntentModal);

if (modal) {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            hideIntentModal();
        }
    });
}

// Credentials Toggle
const toggleCredentialsBtn = document.getElementById('toggleCredentials');
let credentialsVisible = false;

if (toggleCredentialsBtn) {
    toggleCredentialsBtn.addEventListener('click', () => {
        credentialsVisible = !credentialsVisible;
        toggleCredentialsBtn.textContent = credentialsVisible ? 'Hide' : 'Show';

        // Select all secret fields (IDs and Classes)
        const secretInputs = document.querySelectorAll(
            '#postApiSecret, #postAccessSecret, .scrape-api-secret, .scrape-access-secret, .scrape-bearer-token'
        );

        secretInputs.forEach(input => {
            input.type = credentialsVisible ? 'text' : 'password';
        });
    });
}

// --- Settings Functions ---

async function loadSettings() {
    try {
        const res = await fetchWithAuth('/api/settings');
        const settings = await res.json();

        // Posting Credentials (OAuth 2.0 Status)
        const oauthStatusText = document.getElementById('oauthStatusText');
        const connectTwitterBtn = document.getElementById('connectTwitterBtn');
        const disconnectTwitterBtn = document.getElementById('disconnectTwitterBtn');

        if (settings.posting_credentials && settings.posting_credentials.access_token) {
            if (oauthStatusText) oauthStatusText.textContent = 'Account Connected';
            if (oauthStatusText) oauthStatusText.style.color = '#10b981'; // Green
            if (connectTwitterBtn) connectTwitterBtn.style.display = 'none';
            if (disconnectTwitterBtn) disconnectTwitterBtn.style.display = 'inline-block';
        } else {
            if (oauthStatusText) oauthStatusText.textContent = 'Not Connected to Twitter';
            if (oauthStatusText) oauthStatusText.style.color = '#94a3b8'; // Gray
            if (connectTwitterBtn) connectTwitterBtn.style.display = 'inline-flex';
            if (disconnectTwitterBtn) disconnectTwitterBtn.style.display = 'none';
        }

        // Scraping Credentials
        const scrapingAccountsList = document.getElementById('scrapingAccountsList');
        if (scrapingAccountsList) {
            scrapingAccountsList.innerHTML = '';
            if (settings.scraping_credentials && settings.scraping_credentials.length > 0) {
                settings.scraping_credentials.forEach(cred => addScrapingAccount(cred));
            } else {
                // Add one empty default if none exist
                addScrapingAccount();
            }
        }

    } catch (e) {
        console.error('Failed to load settings', e);
        log('Failed to load settings', 'error');
    }
}

// Connect & Disconnect Handlers
const connectTwitterBtn = document.getElementById('connectTwitterBtn');
const disconnectTwitterBtn = document.getElementById('disconnectTwitterBtn');

if (connectTwitterBtn) {
    connectTwitterBtn.addEventListener('click', async () => {
        const originalText = connectTwitterBtn.innerHTML;
        connectTwitterBtn.innerHTML = 'Connecting...';
        connectTwitterBtn.disabled = true;
        try {
            const res = await fetchWithAuth('/api/auth/twitter/login');
            if (res.ok) {
                const data = await res.json();
                if (data.url) {
                    window.location.href = data.url;
                }
            } else {
                showToast("Failed to initialize Twitter Login", "error");
                connectTwitterBtn.innerHTML = originalText;
                connectTwitterBtn.disabled = false;
            }
        } catch (err) {
            showToast("Network error initiating login", "error");
            connectTwitterBtn.innerHTML = originalText;
            connectTwitterBtn.disabled = false;
        }
    });
}

if (disconnectTwitterBtn) {
    disconnectTwitterBtn.addEventListener('click', async () => {
        // To disconnect, we simply send empty posting_credentials. The rest of the settings logic handles it.
        disconnectTwitterBtn.textContent = 'Disconnecting...';
        disconnectTwitterBtn.disabled = true;

        // We need to fetch current scraping creds to not overwrite them
        let scrapingCreds = [];
        document.querySelectorAll('.scraping-account-item').forEach(item => {
            scrapingCreds.push({
                api_key: item.querySelector('.scrape-api-key').value,
                api_secret: item.querySelector('.scrape-api-secret').value,
                access_token: item.querySelector('.scrape-access-token').value,
                access_secret: item.querySelector('.scrape-access-secret').value,
                bearer_token: item.querySelector('.scrape-bearer-token').value
            });
        });

        try {
            const res = await fetchWithAuth('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    posting_credentials: {}, // Empty to indicate disconnect
                    scraping_credentials: scrapingCreds
                })
            });
            if (res.ok) {
                showToast("Twitter Account Disconnected");
                loadSettings(); // Reload UI
            } else {
                showToast("Failed to disconnect", "error");
            }
        } catch (err) {
            showToast("Error disconnecting", "error");
            disconnectTwitterBtn.textContent = 'Disconnect';
            disconnectTwitterBtn.disabled = false;
        }
    });
}


function addScrapingAccount(data = {}) {
    const div = document.createElement('div');
    div.className = 'scraping-account-item glass-panel';
    div.style.marginBottom = '1rem';
    div.style.padding = '1rem';
    div.style.border = '1px solid rgba(255, 255, 255, 0.1)';
    const scrapingAccountsList = document.getElementById('scrapingAccountsList');

    div.innerHTML = `
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                <h4>TwitterAPI.io Account</h4>
                <button class="btn-sm btn-secondary remove-account" style="color: var(--error);">Remove</button>
            </div>
            <div class="form-group">
                <label>API Key (from TwitterAPI.io dashboard)</label>
                <input type="text" class="scrape-api-key" value="${data.api_key || ''}" placeholder="Paste your TwitterAPI.io API Key here">
            </div>
        `;

    div.querySelector('.remove-account').addEventListener('click', () => div.remove());
    if (scrapingAccountsList) scrapingAccountsList.appendChild(div);
}

async function saveSettings() {
    const saveBtn = document.getElementById('saveSettingsBtn');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;

    try {
        // Collect Scraping Creds
        const scrapingCreds = [];
        document.querySelectorAll('.scraping-account-item').forEach(item => {
            scrapingCreds.push({
                api_key: item.querySelector('.scrape-api-key')?.value || ''
            });
        });

        // To prevent clearing posting credentials, we need to send the current active token status.
        // But since our Python backend `api/settings` route completely overwrites settings dict, we must pass it along.
        // Wait, the new logic: if posting_credentials isn't passed from UI, the backend will overwrite with dict unless updated. 
        // So we need to fetch currents first or just use the current loaded state.
        const resInit = await fetchWithAuth('/api/settings');
        const currentSettings = await resInit.json();

        const res = await fetchWithAuth('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                posting_credentials: currentSettings.posting_credentials, // KEEP EXISTING
                scraping_credentials: scrapingCreds
            })
        });

        if (!res.ok) throw new Error('Failed to save settings');

        log('Settings saved successfully', 'success');
        saveBtn.textContent = 'Saved!';
        setTimeout(() => {
            saveBtn.textContent = originalText;
            saveBtn.disabled = false;
        }, 2000);

    } catch (e) {
        console.error('Failed to save settings', e);
        log('Failed to save settings', 'error');
        saveBtn.textContent = 'Error';
        setTimeout(() => {
            saveBtn.textContent = originalText;
            saveBtn.disabled = false;
        }, 2000);
    }
}

// --- ADMIN STATS LOGIC ---
async function loadAdminStats() {
    try {
        const res = await fetchWithAuth('/api/admin/stats');
        if (!res.ok) return;

        const stats = await res.json();
        const tbody = document.getElementById('adminStatsBody');
        if (!tbody) return;

        tbody.innerHTML = ''; // Clear existing

        stats.forEach(userStat => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';

            tr.innerHTML = `
                    <td style="padding: 12px; font-weight: 500;">${userStat.username}</td>
                    <td style="padding: 12px; color: #60a5fa;">${userStat.credits !== undefined ? userStat.credits : 0}</td>
                    <td style="padding: 12px; color: #94a3b8;">${userStat.total_scraped || 0}</td>
                    <td style="padding: 12px; color: #94a3b8;">${userStat.total_generated || 0}</td>
                    <td style="padding: 12px; color: #10b981;">${userStat.total_posted || 0}</td>
                `;
            tbody.appendChild(tr);
        });

    } catch (e) {
        console.error("Error loading admin stats:", e);
    }
}


// Bind refresh button
const refreshAdminStatsBtn = document.getElementById('refreshAdminStats');
if (refreshAdminStatsBtn) {
    refreshAdminStatsBtn.addEventListener('click', loadAdminStats);
}

// Toast Helper
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = type === 'success' ? `Success: ${message}` : `Error: ${message}`;

    container.appendChild(toast);

    // Remove after 3 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Bind Add Credits Button (Opens Modal)
const addCreditsBtn = document.getElementById('addCreditsBtn');
const creditModal = document.getElementById('creditModal');
const creditAmountDisp = document.getElementById('modalCreditAmount');
const creditUserDisp = document.getElementById('modalCreditUser');
const creditConfirmBtn = document.getElementById('creditModalConfirm');
const creditCancelBtn = document.getElementById('creditModalCancel');
const creditCloseBtn = document.getElementById('creditModalClose');

let pendingCreditRequest = null;

// GLOBAL HANDLER for inline onclick fallback
window.handleAddCredits = function () {
    const username = document.getElementById('creditUsername').value;
    const amount = document.getElementById('creditAmount').value;

    if (!username || !amount) {
        showToast('Please enter username and amount', 'error');
        return;
    }

    // Populate Modal
    creditUserDisp.textContent = username;
    creditAmountDisp.textContent = amount;
    pendingCreditRequest = { username, amount: parseInt(amount) };

    // Show Modal
    creditModal.classList.add('active');
};

if (addCreditsBtn && creditModal) {
    addCreditsBtn.addEventListener('click', window.handleAddCredits);

    // Close Modal Logic
    const closeCreditModal = () => {
        creditModal.classList.remove('active');
        pendingCreditRequest = null;
    };

    creditCloseBtn.onclick = closeCreditModal;
    creditCancelBtn.onclick = closeCreditModal;
    window.onclick = (event) => {
        if (event.target == creditModal) closeCreditModal();
    };

    // Confirm Action
    creditConfirmBtn.addEventListener('click', async () => {
        if (!pendingCreditRequest) return;

        creditConfirmBtn.disabled = true;
        creditConfirmBtn.textContent = 'Adding...';

        try {
            const res = await fetchWithAuth('/api/admin/credits', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(pendingCreditRequest)
            });

            const data = await res.json();
            if (res.ok) {
                showToast(`Successfully added ${pendingCreditRequest.amount} credits!`);
                // Refresh stats
                loadAdminStats();
                // Refresh own header if added to self
                loadCurrentUser();
                closeCreditModal();
                // Clear inputs
                document.getElementById('creditUsername').value = '';
                document.getElementById('creditAmount').value = '';
            } else {
                showToast(data.detail || 'Failed to add credits', 'error');
            }
        } catch (e) {
            console.error(e);
            showToast('Network error', 'error');
        } finally {
            creditConfirmBtn.disabled = false;
            creditConfirmBtn.textContent = 'Confirm & Add';
        }
    });
}

async function loadHistory() {
    try {
        const res = await fetchWithAuth('/api/history');
        const historyItems = await res.json();
        const historyList = document.getElementById('historyList');

        if (!historyList) return;

        historyList.innerHTML = '';

        if (historyItems.length === 0) {
            historyList.innerHTML = '<div class="empty-state">No history available</div>';
            return;
        }

        historyItems.forEach(item => {
            const div = document.createElement('div');
            div.className = 'review-item';
            div.innerHTML = `
                    <div class="review-header">
                        <span>ID: ${item.tweet_id}</span>
                        <span>${item.timestamp}</span>
                    </div>
                    <div class="review-text" style="color: #94a3b8; font-size: 0.85rem;">"${item.tweet_text ? item.tweet_text.substring(0, 100) : 'No text'}..."</div>
                    <div class="review-text">${item.reply_text}</div>
                    <div class="review-actions">
                        <span class="badge" style="background: rgba(16, 185, 129, 0.1); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.2);">${item.status || 'Posted'}</span>
                    </div>
                `;
            historyList.appendChild(div);
        });

    } catch (e) {
        console.error('Failed to load history', e);
        log('Failed to load history', 'error');
    }
}

const refreshHistoryBtn = document.getElementById('refreshHistory');
if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener('click', loadHistory);
}

// Profile Modal Logout
const profileLogoutBtn = document.getElementById('profileLogoutBtn');
if (profileLogoutBtn) {
    profileLogoutBtn.addEventListener('click', () => {
        localStorage.removeItem('token');
        window.location.href = '/login.html';
    });
}

});
