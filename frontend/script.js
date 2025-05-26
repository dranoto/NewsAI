// script.js
document.addEventListener('DOMContentLoaded', async () => {
    // Main Feed Elements
    const resultsContainer = document.getElementById('results-container');
    const loadingIndicator = document.getElementById('loading-indicator');
    const loadingText = document.getElementById('loading-text');
    const refreshNewsBtn = document.getElementById('refresh-news-btn');
    const paginationControlsTop = document.getElementById('pagination-controls-top');
    const paginationControlsBottom = document.getElementById('pagination-controls-bottom');
    const feedFilterControls = document.getElementById('feed-filter-controls');

    // Setup Section Elements
    const contentPrefsForm = document.getElementById('content-prefs-form');
    const numArticlesSetupInput = document.getElementById('num_articles_setup');
    const currentNumArticlesDisplay = document.getElementById('current-num-articles-display');

    const addRssFeedForm = document.getElementById('add-rss-feed-form');
    const rssFeedUrlInput = document.getElementById('rss-feed-url-input');
    const rssFeedsListUI = document.getElementById('rss-feeds-list');
    const clearRssFeedsBtn = document.getElementById('clear-rss-feeds-btn');

    // AI Prompts Configuration Elements
    const aiPromptsForm = document.getElementById('ai-prompts-form');
    const summaryPromptInput = document.getElementById('summary-prompt-input');
    const chatPromptInput = document.getElementById('chat-prompt-input');
    const resetPromptsBtn = document.getElementById('reset-prompts-btn');
    const currentSummaryPromptDisplay = document.getElementById('current-summary-prompt-display');
    const currentChatPromptDisplay = document.getElementById('current-chat-prompt-display');
    
    const apiEndpointForm = document.getElementById('api-endpoint-form');
    const apiUrlInput = document.getElementById('api-url');
    const chatApiUrlInput = document.getElementById('chat-api-url');
    const currentApiUrlDisplay = document.getElementById('current-api-url-display');
    const currentChatApiUrlDisplay = document.getElementById('current-chat-api-url-display');

    // Navigation
    const mainFeedSection = document.getElementById('main-feed-section');
    const setupSection = document.getElementById('setup-section');
    const navMainBtn = document.getElementById('nav-main-btn');
    const navSetupBtn = document.getElementById('nav-setup-btn');

    // State Variables
    let rssFeedUrls = []; 
    let SUMMARIES_API_ENDPOINT = '/api/get-news-summaries'; 
    let CHAT_API_ENDPOINT = '/api/chat-with-article';   
    let articlesPerPage = 6; 
    let currentPage = 1;
    let totalPages = 1;
    let totalArticlesAvailable = 0;
    let activeFeedFilter = null; 

    let currentSummaryPrompt = '';
    let currentChatPrompt = '';
    let defaultSummaryPrompt = ''; 
    let defaultChatPrompt = '';   

    // --- Utility Function: Get Feed Name ---
    // Moved to a higher scope to be accessible by multiple functions
    const getFeedName = (url) => {
        if (!url) return 'Unknown Feed';
        try {
            const urlObj = new URL(url);
            let name = urlObj.hostname.replace(/^www\./, '');
            const pathParts = urlObj.pathname.split('/').filter(part => part && !part.toLowerCase().includes('feed') && !part.toLowerCase().includes('rss') && part.length > 2);
            if (pathParts.length > 0) {
                const potentialName = pathParts[pathParts.length - 1].replace(/\.(xml|rss|atom)/i, '');
                if (potentialName.length > 3 && potentialName.length < 25) name = potentialName;
                else if (name.length + potentialName.length < 30 && potentialName) name += ` (${potentialName})`;
            }
            return name.length > 35 ? name.substring(0, 32) + "..." : name;
        } catch (e) {
            // Fallback for invalid URLs or other issues
            const simpleName = url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0];
            return simpleName.length > 35 ? simpleName.substring(0, 32) + "..." : simpleName;
        }
    };

    // --- Chat History Management ---
    function getChatHistory(articleUrl) {
        try {
            return JSON.parse(localStorage.getItem(`chatHistory_${articleUrl}`)) || [];
        } catch (e) {
            console.error("Error parsing chat history from localStorage:", e);
            return []; 
        }
    }

    function saveChatHistory(articleUrl, question, answer) {
        const history = getChatHistory(articleUrl);
        history.push({ question, answer });
        try {
            localStorage.setItem(`chatHistory_${articleUrl}`, JSON.stringify(history));
        } catch (e) { // Corrected line: Removed stray 'M'
            console.error("Error saving chat history to localStorage:", e);
        }
    }

    function renderChatHistory(responseDiv, articleUrl) {
        const history = getChatHistory(articleUrl);
        responseDiv.innerHTML = ''; 
        if (history.length === 0) return; 
        
        history.forEach(chat => {
            const qDiv = document.createElement('div');
            qDiv.classList.add('chat-history-q');
            qDiv.textContent = `You: ${chat.question}`;
            responseDiv.appendChild(qDiv);

            const aDiv = document.createElement('div');
            aDiv.classList.add('chat-history-a');
            aDiv.textContent = `AI: ${chat.answer}`; 
            if (chat.answer && (chat.answer.startsWith("AI Error:") || chat.answer.startsWith("Error:"))) { 
                aDiv.classList.add('error-message');
            }
            responseDiv.appendChild(aDiv);
        });
        if (responseDiv.scrollHeight > responseDiv.clientHeight) {
            responseDiv.scrollTop = responseDiv.scrollHeight;
        }
    }

    // --- Initial Configuration Fetch ---
    async function fetchInitialConfig() {
        try {
            const response = await fetch('/api/initial-config'); 
            if (!response.ok) {
                console.warn('Failed to fetch initial config from backend, using local defaults/localStorage.');
                defaultSummaryPrompt = "Please summarize: {text}"; 
                defaultChatPrompt = "Article: {article_text}\nQuestion: {question}\nAnswer:";
                return; 
            }
            const configData = await response.json();
            console.log("Fetched initial config from backend:", configData);

            if (!localStorage.getItem('rssFeedUrls') && configData.default_rss_feeds && configData.default_rss_feeds.length > 0) {
                rssFeedUrls = configData.default_rss_feeds;
                localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls));
            }
            if (!localStorage.getItem('articlesPerPage') && configData.default_articles_per_page) {
                articlesPerPage = configData.default_articles_per_page;
                localStorage.setItem('articlesPerPage', articlesPerPage.toString());
            }
            defaultSummaryPrompt = configData.default_summary_prompt || "Summarize: {text}";
            defaultChatPrompt = configData.default_chat_prompt || "Context: {article_text}\nQuestion: {question}\nAnswer:";
        } catch (error) {
            console.error('Error fetching initial config:', error);
            defaultSummaryPrompt = "Please summarize the key points of this article: {text}"; 
            defaultChatPrompt = "Based on this article: {article_text}\nWhat is the answer to: {question}?";
        }
    }

    // --- App Initialization ---
    async function initializeAppSettings() {
        await fetchInitialConfig(); 

        rssFeedUrls = JSON.parse(localStorage.getItem('rssFeedUrls')) || []; 
        SUMMARIES_API_ENDPOINT = localStorage.getItem('newsSummariesApiEndpoint') || '/api/get-news-summaries';
        CHAT_API_ENDPOINT = localStorage.getItem('newsChatApiEndpoint') || '/api/chat-with-article';
        articlesPerPage = parseInt(localStorage.getItem('articlesPerPage')) || 6;

        currentSummaryPrompt = localStorage.getItem('customSummaryPrompt') || defaultSummaryPrompt;
        currentChatPrompt = localStorage.getItem('customChatPrompt') || defaultChatPrompt;

        updateSetupUI(); 

        renderRssFeeds(); 
        renderFeedFilterButtons(); 
        showSection('main-feed-section'); 

        if (rssFeedUrls.length > 0) {
            fetchAndDisplaySummaries(true, 1); 
        } else {
            if(resultsContainer) resultsContainer.innerHTML = '<p>Please configure RSS feeds in the Setup tab to see news.</p>';
            updatePaginationUI(0,0,0,0);
            if (feedFilterControls) renderFeedFilterButtons();
        }
    }
    
    function updateSetupUI() {
        if(currentApiUrlDisplay) currentApiUrlDisplay.textContent = SUMMARIES_API_ENDPOINT;
        if(apiUrlInput) apiUrlInput.value = SUMMARIES_API_ENDPOINT;
        if(currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = CHAT_API_ENDPOINT;
        if(chatApiUrlInput) chatApiUrlInput.value = CHAT_API_ENDPOINT;
        if(numArticlesSetupInput) numArticlesSetupInput.value = articlesPerPage;
        if(currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = articlesPerPage;

        if(summaryPromptInput) summaryPromptInput.value = currentSummaryPrompt;
        if(chatPromptInput) chatPromptInput.value = currentChatPrompt;
        if(currentSummaryPromptDisplay) currentSummaryPromptDisplay.textContent = currentSummaryPrompt;
        if(currentChatPromptDisplay) currentChatPromptDisplay.textContent = currentChatPrompt;
    }


    // --- RSS Feed Management (Setup Tab) ---
    function renderRssFeeds() {
        if (!rssFeedsListUI) return;
        rssFeedsListUI.innerHTML = '';
        rssFeedUrls.forEach((feedUrl, index) => {
            const li = document.createElement('li');
            li.textContent = feedUrl;
            const removeBtn = document.createElement('button');
            removeBtn.textContent = 'Remove';
            removeBtn.classList.add('remove-site-btn');
            removeBtn.onclick = () => removeRssFeed(index);
            li.appendChild(removeBtn);
            rssFeedsListUI.appendChild(li);
        });
        if (feedFilterControls) renderFeedFilterButtons(); 
    }

    function addRssFeed(url) {
        const trimmedUrl = url.trim();
        if (trimmedUrl) {
            try { 
                new URL(trimmedUrl); 
                if (!rssFeedUrls.includes(trimmedUrl)) {
                    rssFeedUrls.push(trimmedUrl); 
                    localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls)); 
                    renderRssFeeds(); 
                } else {
                    alert("This RSS feed URL is already in the list.");
                }
            } catch (_) { 
                alert("Please enter a valid URL for the RSS feed."); 
            }
        }
    }
    function removeRssFeed(indexToRemove) {
        const removedFeedUrl = rssFeedUrls[indexToRemove];
        rssFeedUrls.splice(indexToRemove, 1); 
        localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls)); 
        renderRssFeeds();
        if (activeFeedFilter === removedFeedUrl) { 
            activeFeedFilter = null;
            fetchAndDisplaySummaries(false, 1); 
        }
    }
    function clearAllRssFeeds() {
        rssFeedUrls = []; 
        localStorage.removeItem('rssFeedUrls'); 
        renderRssFeeds();
        activeFeedFilter = null; 
        fetchAndDisplaySummaries(false, 1); 
    }

    // --- AI Prompt Configuration (Setup Tab) ---
    if (aiPromptsForm) {
        aiPromptsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newSummaryPrompt = summaryPromptInput.value.trim();
            const newChatPrompt = chatPromptInput.value.trim();

            if (newSummaryPrompt && !newSummaryPrompt.includes("{text}")) {
                alert("Summary prompt must contain the placeholder {text}. Using default if saved empty.");
            }
            if (newChatPrompt && (!newChatPrompt.includes("{article_text}") || !newChatPrompt.includes("{question}"))) {
                 if (!newChatPrompt.includes("{question}")) { 
                    alert("Chat prompt should ideally include {article_text} and {question}, or at least {question}. Using default if saved empty.");
                 } else {
                    console.warn("Chat prompt might be missing {article_text}. This is allowed but might not use article context effectively.");
                 }
            }

            currentSummaryPrompt = newSummaryPrompt || defaultSummaryPrompt;
            currentChatPrompt = newChatPrompt || defaultChatPrompt;

            localStorage.setItem('customSummaryPrompt', currentSummaryPrompt);
            localStorage.setItem('customChatPrompt', currentChatPrompt);
            
            updateSetupUI(); 
            alert('AI Prompts saved!');
        });
    }

    if (resetPromptsBtn) {
        resetPromptsBtn.addEventListener('click', () => {
            if (confirm("Are you sure you want to reset prompts to their default values?")) {
                currentSummaryPrompt = defaultSummaryPrompt;
                currentChatPrompt = defaultChatPrompt;
                localStorage.setItem('customSummaryPrompt', currentSummaryPrompt); 
                localStorage.setItem('customChatPrompt', currentChatPrompt);   
                updateSetupUI();
                alert('Prompts have been reset to defaults.');
            }
        });
    }


    // --- API Endpoint and Preferences Management (Setup Tab) ---
    if (addRssFeedForm) addRssFeedForm.addEventListener('submit', (e) => { e.preventDefault(); addRssFeed(rssFeedUrlInput.value); rssFeedUrlInput.value = ''; });
    if (clearRssFeedsBtn) clearRssFeedsBtn.addEventListener('click', clearAllRssFeeds);
    
    if(apiEndpointForm) {
        apiEndpointForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newSummariesApiUrl = apiUrlInput.value.trim();
            const newChatApiUrl = chatApiUrlInput.value.trim();
            let updated = false;
            if (newSummariesApiUrl) {
                SUMMARIES_API_ENDPOINT = newSummariesApiUrl; localStorage.setItem('newsSummariesApiEndpoint', SUMMARIES_API_ENDPOINT);
                updated = true;
            }
            if (newChatApiUrl) {
                CHAT_API_ENDPOINT = newChatApiUrl; localStorage.setItem('newsChatApiEndpoint', CHAT_API_ENDPOINT);
                updated = true;
            }
            if(updated) {
                updateSetupUI(); 
                alert('API Endpoints updated!');
            }
        });
    }

    if (contentPrefsForm) {
        contentPrefsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newArticlesPerPage = parseInt(numArticlesSetupInput.value);
            if (newArticlesPerPage >= 1 && newArticlesPerPage <= 12) {
                articlesPerPage = newArticlesPerPage; 
                localStorage.setItem('articlesPerPage', articlesPerPage.toString());
                updateSetupUI(); 
                alert('Content preferences saved! Articles per page set to ' + articlesPerPage);
                currentPage = 1; 
                fetchAndDisplaySummaries(false, 1); 
            } else { 
                alert('Please enter a number of articles per page between 1 and 12.'); 
            }
        });
    }


    // --- Feed Filter Button Management ---
    function renderFeedFilterButtons() {
        if (!feedFilterControls) return;
        feedFilterControls.innerHTML = ''; 

        const allFeedsButton = document.createElement('button');
        allFeedsButton.textContent = 'All Feeds';
        allFeedsButton.onclick = () => {
            if (activeFeedFilter === null) return; 
            activeFeedFilter = null;
            updateFilterButtonStyles();
            fetchAndDisplaySummaries(false, 1); 
        };
        feedFilterControls.appendChild(allFeedsButton);
        
        rssFeedUrls.forEach(feedUrl => {
            const feedButton = document.createElement('button');
            feedButton.textContent = getFeedName(feedUrl); // Now calls the globally scoped getFeedName
            feedButton.setAttribute('data-feedurl', feedUrl);
            feedButton.onclick = () => {
                if (activeFeedFilter === feedUrl) return; 
                activeFeedFilter = feedUrl;
                updateFilterButtonStyles();
                fetchAndDisplaySummaries(false, 1); 
            };
            feedFilterControls.appendChild(feedButton);
        });
        updateFilterButtonStyles();
    }

    function updateFilterButtonStyles() {
        if (!feedFilterControls) return;
        const buttons = feedFilterControls.querySelectorAll('button');
        buttons.forEach(button => {
            const feedUrlAttr = button.getAttribute('data-feedurl');
            if (activeFeedFilter === null && button.textContent === 'All Feeds') {
                button.classList.add('active');
            } else if (feedUrlAttr && feedUrlAttr === activeFeedFilter) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    }

    // --- Fetching and Displaying News Summaries ---
    async function fetchAndDisplaySummaries(forceRssRefresh = false, page = 1) {
        if (!resultsContainer || !loadingIndicator || !loadingText) return;
        
        currentPage = page; 
        const activeFeedName = activeFeedFilter ? getFeedName(activeFeedFilter) : 'All Feeds'; // Now calls the globally scoped getFeedName
        loadingText.textContent = `Fetching page ${currentPage} for ${activeFeedName}...`;
        loadingIndicator.style.display = 'flex'; 
        if(resultsContainer) resultsContainer.innerHTML = ''; 
        if(page === 1) { 
            updatePaginationUI(0,0,0,0);
        }

        let feedsForPayload = [];
        if (forceRssRefresh) {
            feedsForPayload = []; 
        } else if (activeFeedFilter) {
            feedsForPayload = [activeFeedFilter];
        } else {
            feedsForPayload = rssFeedUrls;
        }
        
        const payload = { 
            page: currentPage, 
            page_size: articlesPerPage, 
            rss_feed_urls: feedsForPayload, 
            force_refresh_rss: forceRssRefresh,
            summary_prompt: (currentSummaryPrompt !== defaultSummaryPrompt) ? currentSummaryPrompt : null, 
        };
        
        try {
            const response = await fetch(SUMMARIES_API_ENDPOINT, { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            });
            if (!response.ok) { 
                const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` })); 
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`); 
            }
            const data = await response.json(); 
            displayResults(data.processed_articles_on_page); 
            totalArticlesAvailable = data.total_articles_available; 
            totalPages = data.total_pages;
            currentPage = data.requested_page; 
            updatePaginationUI(currentPage, totalPages, articlesPerPage, totalArticlesAvailable);

            if (rssFeedUrls.length === 0 && data.processed_articles_on_page.length === 0) {
                 if(resultsContainer) resultsContainer.innerHTML = '<p>No RSS feeds configured. Please add some in the Setup tab.</p>';
            } else if (data.processed_articles_on_page.length === 0 && totalArticlesAvailable === 0) {
                 if(resultsContainer) resultsContainer.innerHTML = `<p>No articles found for the current filter (${activeFeedName}). Try a different filter or refresh.</p>`;
            }

        } catch (error) { 
            console.error('Error fetching summaries:', error); 
            if(resultsContainer) resultsContainer.innerHTML = `<p class="error-message">Error fetching summaries: ${error.message}. Please check API logs and network.</p>`; 
            updatePaginationUI(0,0,0,0); 
        }
        finally { loadingIndicator.style.display = 'none'; }
    }

    if (refreshNewsBtn) {
        refreshNewsBtn.addEventListener('click', () => {
            activeFeedFilter = null; 
            if (feedFilterControls) renderFeedFilterButtons(); 
            fetchAndDisplaySummaries(true, 1); 
        });
    }
    
    // --- UI Update Functions (Pagination, Results Display) ---
    function updatePaginationUI(currentPg, totalPgs, pgSize, totalItems) {
        const renderControls = (container) => {
            if (!container) return; 
            container.innerHTML = ''; 
            if (totalPgs <= 0) return;

            const prevButton = document.createElement('button'); 
            prevButton.textContent = '‹ Previous';
            prevButton.disabled = currentPg <= 1; 
            prevButton.onclick = () => fetchAndDisplaySummaries(false, currentPg - 1);
            container.appendChild(prevButton);

            const pageInfo = document.createElement('span'); 
            pageInfo.classList.add('page-info');
            pageInfo.textContent = `Page ${currentPg} of ${totalPgs} (${totalItems} articles)`;
            container.appendChild(pageInfo);

            const nextButton = document.createElement('button'); 
            nextButton.textContent = 'Next ›';
            nextButton.disabled = currentPg >= totalPgs; 
            nextButton.onclick = () => fetchAndDisplaySummaries(false, currentPg + 1);
            container.appendChild(nextButton);
        };
        renderControls(paginationControlsTop); 
        renderControls(paginationControlsBottom);
    }

    function displayResults(articles) {
        if (!articles || articles.length === 0) {
            return;
        }
        articles.forEach((article, index) => {
            const uniqueArticleId = `article-${currentPage}-${index}`; 

            const articleCard = document.createElement('div'); articleCard.classList.add('article-card');
            articleCard.setAttribute('id', uniqueArticleId);
            
            const titleEl = document.createElement('h3'); titleEl.textContent = article.title || 'No Title Provided'; articleCard.appendChild(titleEl);
            const metaInfo = document.createElement('div'); metaInfo.classList.add('article-meta-info');
            if (article.publisher) { const p = document.createElement('span'); p.classList.add('article-publisher'); p.textContent = `Source: ${article.publisher}`; metaInfo.appendChild(p); }
            if (article.published_date) { const d = document.createElement('span'); d.classList.add('article-published-date'); try { d.textContent = `Published: ${new Date(article.published_date).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric', hour:'numeric', minute:'numeric' })}`; } catch (e) { d.textContent = `Published: ${article.published_date}`; } metaInfo.appendChild(d); }
            if (metaInfo.hasChildNodes()) articleCard.appendChild(metaInfo);

            if (article.url) { const l = document.createElement('a'); l.href = article.url; l.textContent = 'Read Full Article'; l.classList.add('source-link'); l.target = '_blank'; l.rel = 'noopener noreferrer'; articleCard.appendChild(l); }
            if (article.summary) { const s = document.createElement('p'); s.classList.add('summary'); s.textContent = article.summary; articleCard.appendChild(s); }
            if (article.error_message) { const err = document.createElement('p'); err.classList.add('error-message'); err.textContent = `Note: ${article.error_message}`; articleCard.appendChild(err); }
            
            if (article.url && !article.error_message && CHAT_API_ENDPOINT) { 
                const chatSectionDiv = document.createElement('div'); 
                chatSectionDiv.classList.add('chat-section');
                const chatTitleEl = document.createElement('h4'); 
                chatTitleEl.textContent = 'Ask about this article:'; 
                chatSectionDiv.appendChild(chatTitleEl);
                const chatInputGroupDiv = document.createElement('div'); 
                chatInputGroupDiv.classList.add('chat-input-group');
                const chatInputEl = document.createElement('input'); 
                chatInputEl.setAttribute('type', 'text'); 
                chatInputEl.setAttribute('placeholder', 'Your question...'); 
                chatInputEl.classList.add('chat-question-input'); 
                chatInputEl.setAttribute('id', `chat-input-${uniqueArticleId}`); 
                chatInputGroupDiv.appendChild(chatInputEl);
                const chatButtonEl = document.createElement('button'); 
                chatButtonEl.textContent = 'Ask'; 
                chatButtonEl.classList.add('chat-ask-button'); 
                chatButtonEl.onclick = () => handleArticleChat(article.url, uniqueArticleId); 
                chatInputEl.addEventListener('keypress', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault(); 
                        handleArticleChat(article.url, uniqueArticleId);
                    }
                });
                chatInputGroupDiv.appendChild(chatButtonEl);
                chatSectionDiv.appendChild(chatInputGroupDiv); 
                const chatResponseAreaDiv = document.createElement('div'); 
                chatResponseAreaDiv.classList.add('chat-response'); 
                chatResponseAreaDiv.setAttribute('id', `chat-response-${uniqueArticleId}`);
                renderChatHistory(chatResponseAreaDiv, article.url); 
                chatSectionDiv.appendChild(chatResponseAreaDiv);
                articleCard.appendChild(chatSectionDiv);
            }
            resultsContainer.appendChild(articleCard);
        });
    }

    // --- Article Chat Handling ---
    async function handleArticleChat(articleUrl, uniqueArticleCardId) {
        const questionInput = document.getElementById(`chat-input-${uniqueArticleCardId}`);
        const responseDiv = document.getElementById(`chat-response-${uniqueArticleCardId}`);
        const askButton = questionInput.nextElementSibling; 

        if (!questionInput || !responseDiv) return;
        const question = questionInput.value.trim();
        if (!question) { alert('Please enter a question.'); return; }

        const qDiv = document.createElement('div');
        qDiv.classList.add('chat-history-q');
        qDiv.textContent = `You: ${question}`;
        responseDiv.appendChild(qDiv);

        const loadingChatP = document.createElement('p');
        loadingChatP.classList.add('chat-loading');
        loadingChatP.textContent = 'AI is thinking...';
        responseDiv.appendChild(loadingChatP);
        if (responseDiv.scrollHeight > responseDiv.clientHeight) responseDiv.scrollTop = responseDiv.scrollHeight;

        questionInput.value = '';
        questionInput.disabled = true;
        if (askButton) askButton.disabled = true;

        try {
            const payload = { 
                article_url: articleUrl, 
                question: question,
                chat_prompt: (currentChatPrompt !== defaultChatPrompt) ? currentChatPrompt : null 
            };
            const response = await fetch(CHAT_API_ENDPOINT, { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            });
            
            loadingChatP.remove();

            if (!response.ok) { 
                const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` })); 
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`); 
            }
            const data = await response.json();
            const answer = data.answer || "No answer received.";
            
            saveChatHistory(articleUrl, question, answer); 
            
            const aDiv = document.createElement('div');
            aDiv.classList.add('chat-history-a');
            aDiv.textContent = `AI: ${answer}`;
            if (data.error_message || answer.startsWith("Error:")) { 
                aDiv.classList.add('error-message');
                aDiv.textContent = `AI: ${data.error_message || answer}`; 
            }
            responseDiv.appendChild(aDiv);

        } catch (error) { 
            console.error('Error during article chat:', error); 
            const errorDiv = document.createElement('div');
            errorDiv.classList.add('chat-history-a', 'error-message');
            errorDiv.textContent = `AI Error: ${error.message}`;
            responseDiv.appendChild(errorDiv);
            saveChatHistory(articleUrl, question, `AI Error: ${error.message}`); 
        } finally { 
            questionInput.disabled = false; 
            if(askButton) askButton.disabled = false;
            if (responseDiv.scrollHeight > responseDiv.clientHeight) responseDiv.scrollTop = responseDiv.scrollHeight;
            questionInput.focus(); 
        }
    }
    
    // --- Navigation / Section Visibility ---
    function showSection(sectionId) {
        if (mainFeedSection) mainFeedSection.classList.remove('active'); 
        if (setupSection) setupSection.classList.remove('active');
        if (navMainBtn) navMainBtn.classList.remove('active'); 
        if (navSetupBtn) navSetupBtn.classList.remove('active');

        const sectionToShow = document.getElementById(sectionId); 
        if (sectionToShow) sectionToShow.classList.add('active');
        
        if (sectionId === 'main-feed-section' && navMainBtn) {
            navMainBtn.classList.add('active');
        } else if (sectionId === 'setup-section' && navSetupBtn) {
            navSetupBtn.classList.add('active');
        }
    }

    // --- Initialize Event Listeners for Navigation ---
    if (navMainBtn) navMainBtn.addEventListener('click', () => showSection('main-feed-section'));
    if (navSetupBtn) navSetupBtn.addEventListener('click', () => showSection('setup-section'));
    
    // --- Final Initialization Call ---
    await initializeAppSettings(); 
});
