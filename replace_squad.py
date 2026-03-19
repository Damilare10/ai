import re

with open('static/dashboard.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update variable names
content = content.replace("const paystackBtn = document.getElementById('paystackCheckoutBtn');", "const squadBtn = document.getElementById('squadCheckoutBtn');")
content = content.replace("const customPaystackBtn = document.getElementById('customPaystackBtn');", "const customSquadBtn = document.getElementById('customSquadBtn');")
content = content.replace("// --- PAYSTACK INTEGRATION ---", "// --- SQUAD INTEGRATION ---")

# 2. Extract and replace the initiatePaystackCheckout function
old_func = re.search(r"async function initiatePaystackCheckout[\s\S]*?^    }", content, re.MULTILINE | re.DOTALL)
if old_func:
    squad_func = """async function initiateSquadCheckout(amountNgn, creditsToAdd) {
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
                                alert(`Payment successful! Added ${resData.credits_added} credits.`);
                                loadCurrentUser(); // Refresh credits
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
    }"""
    content = content.replace(old_func.group(0), squad_func)
else:
    print("Could not find initiatePaystackCheckout")

# 3. Update the button event listeners
old_btns = re.search(r"if \(paystackBtn\) \{[\s\S]*?}\n\n    if \(customPaystackBtn\) \{[\s\S]*?}\n", content, re.MULTILINE | re.DOTALL)
if old_btns:
    squad_btns = """if (squadBtn) {
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
"""
    content = content.replace(old_btns.group(0), squad_btns)
else:
    print("Could not find event listeners for buttons")

with open('static/dashboard.js', 'w', encoding='utf-8') as f:
    f.write(content)
print("Replaced content successfully.")
