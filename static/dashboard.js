document.addEventListener('DOMContentLoaded', () => {
    // --- GLOBAL VARIABLES START ---
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = '/login.html';
        return; // Stop execution if no token
    }

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
    initChart();
    loadStats();
    loadQueue(); // Load persisted queue items
    loadCurrentUser();
    pollStatus(); // Start polling
    setInterval(pollStatus, 2000); // Poll every 2 seconds

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
            // 1. Get Status
            const statusRes = await fetchWithAuth('/api/batch/status');
            const status = await statusRes.json();

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

            // 2. Get Logs
            const logsRes = await fetchWithAuth('/api/logs?limit=50');
            const logs = await logsRes.json();

            // Filter for new logs only
            const newLogs = logs.filter(log => log.id > maxSeenLogId);

            if (newLogs.length > 0) {
                newLogs.forEach(log => {
                    // Update maxSeenLogId
                    if (log.id > maxSeenLogId) {
                        maxSeenLogId = log.id;
                    }

                    // Only display if it meets the clear filter
                    if (log.id > minLogIdToDisplay) {
                        const div = document.createElement('div');
                        div.className = `log-entry ${log.level.toLowerCase()}`;
                        div.textContent = `[${log.timestamp}] ${log.message}`;
                        consoleLog.appendChild(div);
                    }
                });
                consoleLog.scrollTop = consoleLog.scrollHeight;
            }

            // 3. Refresh Queue (to show new items automatically)
            await loadQueue();

        } catch (e) {
            console.error('Polling error:', e);
        }
    }

    async function startBatchProcessing() {
        if (isProcessing) return;

        const rawText = urlInput.value;
        const urlRegex = /(?:https?:\/\/)?(?:www\.)?(?:x|twitter)\.com\/(?:[a-zA-Z0-9_]+\/status\/[0-9]+|intent\/(?:tweet|like)\?[^\s]+)/g;
        const urls = rawText.match(urlRegex) || [];

        if (urls.length === 0) {
            log('No valid X/Twitter URLs found.', 'error');
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
                    <button class="btn-sm btn-secondary btn-copy" title="Copy to Clipboard">📋</button>
                    <button class="btn-sm btn-secondary btn-intent" title="Open in X">𝕏</button>
                    <button class="btn-sm btn-secondary btn-done" title="Mark as Done">✅</button>
                </div>
                <div class="action-group">
                    <button class="btn-sm btn-discard">Discard</button>
                    <button class="btn-sm btn-approve">Post Reply</button>
                </div>
            </div>
                `;

        // Bind events
        const approveBtn = item.querySelector('.btn-approve');
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

        // 1. Post Reply
        approveBtn.addEventListener('click', () => {
            const text = getCurrentText();
            if (!text.trim()) {
                alert("Cannot post empty reply!");
                return;
            }
            postReply(item, tweetId, text);
        });

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
                copyBtn.textContent = '✅';
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


    async function postReply(itemElement, tweetId, replyText) {
        const btn = itemElement.querySelector('.btn-approve');
        btn.disabled = true;
        btn.textContent = 'Posting...';
        const tweetText = itemElement.dataset.tweetText || null;

        // FIX: Add to ignore list immediately
        const queueId = itemElement.dataset.queueId ? parseInt(itemElement.dataset.queueId) : null;
        if (queueId && typeof locallyDeletedIds !== 'undefined') {
            locallyDeletedIds.add(queueId);
        }

        try {
            const response = await fetchWithAuth('/api/post', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reply_text: replyText,
                    reply_to_id: tweetId,
                    tweet_text: tweetText
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                if (response.status === 429) {
                    throw new Error("Daily posting limit reached (50/day). Try again tomorrow.");
                }
                throw new Error(errorData.detail || 'Post failed');
            }

            // Remove from queue if it has a queueId
            if (itemElement.dataset.queueId) {
                try {
                    await fetchWithAuth(`/api/queue/${itemElement.dataset.queueId}`, { method: 'DELETE' });
                } catch (e) {
                    console.error('Failed to remove from queue', e);
                }
            }

            log(`Successfully posted reply to ${tweetId} `, 'success');
            itemElement.remove();
            updateQueueCount();
            loadStats(); // Refresh stats
        } catch (error) {
            log(`Failed to post to ${tweetId}: ${error.message} `, 'error');
            btn.disabled = false;
            btn.textContent = 'Post Reply';

            // Revert ignore list if failed
            // We need to access queueId here, but it's defined in the upper scope now
            const queueId = itemElement.dataset.queueId ? parseInt(itemElement.dataset.queueId) : null;
            if (queueId && typeof locallyDeletedIds !== 'undefined') {
                locallyDeletedIds.delete(queueId);
            }
        }
    }

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
                    // Add a little user icon + the name
                    usernameEl.innerHTML = `👤 ${user.username} `;
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
            console.error('Failed to load stats', e);
        }
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
            toggleCredentialsBtn.textContent = credentialsVisible ? '🙈' : '👁️';

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

            // Posting Credentials
            if (settings.posting_credentials) {
                const apiKey = document.getElementById('postApiKey');
                if (apiKey) apiKey.value = settings.posting_credentials.api_key || '';
                const apiSecret = document.getElementById('postApiSecret');
                if (apiSecret) apiSecret.value = settings.posting_credentials.api_secret || '';
                const accessToken = document.getElementById('postAccessToken');
                if (accessToken) accessToken.value = settings.posting_credentials.access_token || '';
                const accessSecret = document.getElementById('postAccessSecret');
                if (accessSecret) accessSecret.value = settings.posting_credentials.access_secret || '';
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

    function addScrapingAccount(data = {}) {
        const div = document.createElement('div');
        div.className = 'scraping-account-item glass-panel';
        div.style.marginBottom = '1rem';
        div.style.padding = '1rem';
        div.style.border = '1px solid rgba(255, 255, 255, 0.1)';
        const scrapingAccountsList = document.getElementById('scrapingAccountsList');

        div.innerHTML = `
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                <h4>Account Credentials</h4>
                <button class="btn-sm btn-secondary remove-account" style="color: var(--error);">Remove</button>
            </div>
            <div class="form-group">
                <label>API Key</label>
                <input type="text" class="scrape-api-key" value="${data.api_key || ''}" placeholder="API Key">
            </div>
            <div class="form-group">
                <label>API Secret</label>
                <input type="password" class="scrape-api-secret" value="${data.api_secret || ''}" placeholder="API Secret">
            </div>
            <div class="form-group">
                <label>Access Token</label>
                <input type="text" class="scrape-access-token" value="${data.access_token || ''}" placeholder="Access Token">
            </div>
            <div class="form-group">
                <label>Access Secret</label>
                <input type="password" class="scrape-access-secret" value="${data.access_secret || ''}" placeholder="Access Secret">
            </div>
            <div class="form-group">
                <label>Bearer Token</label>
                <input type="password" class="scrape-bearer-token" value="${data.bearer_token || ''}" placeholder="Bearer Token (Required for v2)">
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
            // Collect Posting Creds
            const postingCreds = {
                api_key: document.getElementById('postApiKey').value,
                api_secret: document.getElementById('postApiSecret').value,
                access_token: document.getElementById('postAccessToken').value,
                access_secret: document.getElementById('postAccessSecret').value
            };

            // Collect Scraping Creds
            const scrapingCreds = [];
            document.querySelectorAll('.scraping-account-item').forEach(item => {
                scrapingCreds.push({
                    api_key: item.querySelector('.scrape-api-key').value,
                    api_secret: item.querySelector('.scrape-api-secret').value,
                    access_token: item.querySelector('.scrape-access-token').value,
                    access_secret: item.querySelector('.scrape-access-secret').value,
                    bearer_token: item.querySelector('.scrape-bearer-token').value
                });
            });

            const res = await fetchWithAuth('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    posting_credentials: postingCreds,
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
    if (refreshAdminStatsBtn) {
        refreshAdminStatsBtn.addEventListener('click', loadAdminStats);
    }

    // Bind Add Credits Button
    const addCreditsBtn = document.getElementById('addCreditsBtn');
    if (addCreditsBtn) {
        addCreditsBtn.addEventListener('click', async () => {
            const usernameInput = document.getElementById('creditUsername');
            const amountInput = document.getElementById('creditAmount');
            const username = usernameInput.value;
            const amount = parseInt(amountInput.value);

            if (!username || !amount) {
                log('Please enter username and amount', 'error');
                return;
            }

            addCreditsBtn.disabled = true;
            addCreditsBtn.textContent = 'Adding...';

            try {
                const res = await fetchWithAuth('/api/admin/credits', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, amount })
                });

                const data = await res.json();
                if (res.ok) {
                    log(data.message || 'Credits added', 'success');
                    loadAdminStats(); // Refresh table
                    usernameInput.value = '';
                    amountInput.value = '';
                } else {
                    log(data.detail || 'Failed to add credits', 'error');
                }
            } catch (e) {
                log('Error connecting to server', 'error');
            } finally {
                addCreditsBtn.disabled = false;
                addCreditsBtn.textContent = 'Add';
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

});
