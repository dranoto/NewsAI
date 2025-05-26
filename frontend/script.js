// script.js
document.addEventListener('DOMContentLoaded', async () => {
    console.log("SCRIPT.JS: DOMContentLoaded event fired. Script execution starting..."); 

    // --- DOM Element References ---
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

    const globalRssSettingsForm = document.getElementById('global-rss-settings-form');
    const rssFetchIntervalInput = document.getElementById('rss-fetch-interval-input');
    const currentRssFetchIntervalDisplay = document.getElementById('current-rss-fetch-interval-display');

    const addRssFeedForm = document.getElementById('add-rss-feed-form');
    const rssFeedUrlInput = document.getElementById('rss-feed-url-input');
    const rssFeedNameInput = document.getElementById('rss-feed-name-input');
    const rssFeedIntervalInput = document.getElementById('rss-feed-interval-input');
    const rssFeedsListUI = document.getElementById('rss-feeds-list');

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

    const mainFeedSection = document.getElementById('main-feed-section');
    const setupSection = document.getElementById('setup-section');
    const navMainBtn = document.getElementById('nav-main-btn');
    const navSetupBtn = document.getElementById('nav-setup-btn');

    const deleteOldDataBtn = document.getElementById('delete-old-data-btn');
    const daysOldInput = document.getElementById('days-old-input');
    const deleteStatusMessage = document.getElementById('delete-status-message');

    const regenerateSummaryModal = document.getElementById('regenerate-summary-modal');
    const closeRegenerateModalBtn = document.getElementById('close-regenerate-modal-btn');
    const regeneratePromptForm = document.getElementById('regenerate-prompt-form');
    const modalSummaryPromptInput = document.getElementById('modal-summary-prompt-input');
    const modalArticleIdInput = document.getElementById('modal-article-id-input');
    const modalUseDefaultPromptBtn = document.getElementById('modal-use-default-prompt-btn');

    // --- State Variables ---
    let dbFeedSources = []; 
    let SUMMARIES_API_ENDPOINT = '/api/get-news-summaries'; 
    let CHAT_API_ENDPOINT_BASE = '/api'; 
    let articlesPerPage = 6; 
    let currentPage = 1;
    let totalPages = 1;
    let totalArticlesAvailable = 0;
    let activeFeedFilterIds = []; 

    let currentSummaryPrompt = '';
    let currentChatPrompt = '';
    let defaultSummaryPrompt = ''; 
    let defaultChatPrompt = '';   
    let globalRssFetchInterval = 60; 

    // --- Utility Function: Get Feed Name (from dbFeedSources) ---
    const getFeedNameById = (feedId) => {
        const feed = dbFeedSources.find(f => f.id === feedId);
        return feed ? (feed.name || feed.url.split('/')[2].replace(/^www\./, '') || 'Unknown Feed') : 'Unknown Feed';
    };
    const getFeedNameByUrl = (url) => { 
        if (!url) return 'Unknown Feed';
        try {
            const urlObj = new URL(url);
            let name = urlObj.hostname.replace(/^www\./, '');
            const pathParts = urlObj.pathname.split('/').filter(part => part && !part.toLowerCase().includes('feed') && !part.toLowerCase().includes('rss') && part.length > 2);
            if (pathParts.length > 0) {
                const potentialName = pathParts[pathParts.length - 1].replace(/\.(xml|rss|atom)/i, '');
                if (potentialName.length > 3 && potentialName.length < 25) name = potentialName;
                else if (name.length + (potentialName?.length || 0) < 30 && potentialName) name += ` (${potentialName})`;
            }
            return name.length > 35 ? name.substring(0, 32) + "..." : name;
        } catch (e) {
            const simpleName = url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0];
            return simpleName.length > 35 ? simpleName.substring(0, 32) + "..." : simpleName;
        }
    };

    // --- Chat History Management (Now Fetches from Backend) ---
    async function fetchChatHistory(articleId, responseDiv) {
        if (!responseDiv) {
            console.error("fetchChatHistory: responseDiv is null for articleId", articleId);
            return;
        }
        responseDiv.innerHTML = '<p class="chat-loading">Loading chat history...</p>'; 
        try {
            const chatHistoryUrl = `${CHAT_API_ENDPOINT_BASE}/article/${articleId}/chat-history`;
            const response = await fetch(chatHistoryUrl);
            if (!response.ok) {
                console.error(`Failed to fetch chat history for article ${articleId}: ${response.status}`);
                responseDiv.innerHTML = `<p class="error-message">Could not load chat history (Status: ${response.status}).</p>`;
                return;
            }
            const history = await response.json();
            renderChatHistory(responseDiv, history, articleId); 
        } catch (error) {
            console.error('Error fetching chat history:', error);
            responseDiv.innerHTML = '<p class="error-message">Error loading chat history.</p>';
        }
    }

    function renderChatHistory(responseDiv, historyArray, articleId) { 
        if (!responseDiv) {
            return;
        }
        responseDiv.innerHTML = ''; 
        if (!historyArray || historyArray.length === 0) {
            return; 
        } 
        
        historyArray.forEach(chat => {
            const qDiv = document.createElement('div');
            qDiv.classList.add('chat-history-q');
            qDiv.textContent = `You: ${chat.question}`;
            responseDiv.appendChild(qDiv);

            const aDiv = document.createElement('div');
            aDiv.classList.add('chat-history-a');
            aDiv.textContent = `AI: ${chat.answer || "Processing..."}`; 
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
        console.log("SCRIPT.JS: fetchInitialConfig: Starting...");
        try {
            const response = await fetch('/api/initial-config'); 
            if (!response.ok) {
                console.warn('SCRIPT.JS: fetchInitialConfig: Failed to fetch initial config from backend.');
                defaultSummaryPrompt = "Please summarize: {text}"; 
                defaultChatPrompt = "Article: {article_text}\nQuestion: {question}\nAnswer:";
                globalRssFetchInterval = 60;
                dbFeedSources = []; 
                return; 
            }
            const configData = await response.json();
            console.log("SCRIPT.JS: fetchInitialConfig: Received configData:", configData);

            if (!localStorage.getItem('articlesPerPage') && configData.default_articles_per_page) {
                articlesPerPage = configData.default_articles_per_page;
                localStorage.setItem('articlesPerPage', articlesPerPage.toString());
            }
            
            defaultSummaryPrompt = configData.default_summary_prompt || "Summarize: {text}";
            defaultChatPrompt = configData.default_chat_prompt || "Context: {article_text}\nQuestion: {question}\nAnswer:";
            globalRssFetchInterval = configData.default_rss_fetch_interval_minutes || 60;
            dbFeedSources = configData.all_db_feed_sources || [];
            console.log("SCRIPT.JS: fetchInitialConfig: dbFeedSources set to:", dbFeedSources);

        } catch (error) {
            console.error('SCRIPT.JS: Error fetching initial config:', error);
            defaultSummaryPrompt = "Please summarize the key points of this article: {text}"; 
            defaultChatPrompt = "Based on this article: {article_text}\nWhat is the answer to: {question}?";
            globalRssFetchInterval = 60;
            dbFeedSources = [];
        }
        console.log("SCRIPT.JS: fetchInitialConfig: Finished.");
    }

    // --- App Initialization ---
    async function initializeAppSettings() {
        console.log("SCRIPT.JS: initializeAppSettings: Starting...");
        await fetchInitialConfig(); 

        SUMMARIES_API_ENDPOINT = localStorage.getItem('newsSummariesApiEndpoint') || '/api/get-news-summaries';
        const chatApiUrlFromStorage = localStorage.getItem('newsChatApiEndpoint');
        if (chatApiUrlFromStorage) {
            CHAT_API_ENDPOINT_BASE = chatApiUrlFromStorage.startsWith('/api/chat-with-article') ? '/api' : chatApiUrlFromStorage;
        } else {
            CHAT_API_ENDPOINT_BASE = '/api';
        }

        articlesPerPage = parseInt(localStorage.getItem('articlesPerPage')) || articlesPerPage; 

        currentSummaryPrompt = localStorage.getItem('customSummaryPrompt') || defaultSummaryPrompt;
        currentChatPrompt = localStorage.getItem('customChatPrompt') || defaultChatPrompt;

        updateSetupUI(); 
        renderRssFeedsListUI(); 
        renderFeedFilterButtons(); 
        showSection('main-feed-section'); 

        console.log("SCRIPT.JS: initializeAppSettings: Checking dbFeedSources.length:", dbFeedSources.length);
        if (dbFeedSources.length > 0) {
            activeFeedFilterIds = []; 
            console.log("SCRIPT.JS: initializeAppSettings: Calling fetchAndDisplaySummaries for the first time.");
            fetchAndDisplaySummaries(false, 1); 
        } else {
            console.log("SCRIPT.JS: initializeAppSettings: No DB feed sources found, not calling fetchAndDisplaySummaries initially.");
            if(resultsContainer) resultsContainer.innerHTML = '<p>No RSS feeds configured in the database. Please add some in the Setup tab.</p>';
            updatePaginationUI(0,0,0,0);
            if (feedFilterControls) renderFeedFilterButtons(); 
        }
        console.log("SCRIPT.JS: initializeAppSettings: Finished.");
    }
    
    function updateSetupUI() {
        if(currentApiUrlDisplay) currentApiUrlDisplay.textContent = SUMMARIES_API_ENDPOINT;
        if(apiUrlInput) apiUrlInput.value = SUMMARIES_API_ENDPOINT;
        if(currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = `${CHAT_API_ENDPOINT_BASE}/chat-with-article`; 
        if(chatApiUrlInput) chatApiUrlInput.value = `${CHAT_API_ENDPOINT_BASE}/chat-with-article`;

        if(numArticlesSetupInput) numArticlesSetupInput.value = articlesPerPage;
        if(currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = articlesPerPage;

        if(summaryPromptInput) summaryPromptInput.value = currentSummaryPrompt;
        if(chatPromptInput) chatPromptInput.value = currentChatPrompt;
        if(currentSummaryPromptDisplay) currentSummaryPromptDisplay.textContent = currentSummaryPrompt;
        if(currentChatPromptDisplay) currentChatPromptDisplay.textContent = currentChatPrompt;

        if(rssFetchIntervalInput) rssFetchIntervalInput.value = globalRssFetchInterval;
        if(currentRssFetchIntervalDisplay) currentRssFetchIntervalDisplay.textContent = globalRssFetchInterval;
    }

    // --- RSS Feed Management (Setup Tab - interacts with DB via API) ---
    async function loadAndRenderDbFeeds() { 
        try {
            const response = await fetch('/api/feeds');
            if (!response.ok) {
                console.error("Failed to fetch feed sources from DB:", response.status);
                alert("Error: Could not load feed sources from database.");
                dbFeedSources = [];
            } else {
                dbFeedSources = await response.json();
            }
        } catch (error) {
            console.error("Error fetching DB feed sources:", error);
            alert("Error: Could not connect to API to load feed sources.");
            dbFeedSources = [];
        }
        renderRssFeedsListUI();
        renderFeedFilterButtons();
    }

    function renderRssFeedsListUI() { 
        if (!rssFeedsListUI) return;
        rssFeedsListUI.innerHTML = '';
        if (dbFeedSources.length === 0) {
            rssFeedsListUI.innerHTML = '<li>No RSS feeds configured in the database.</li>';
            return;
        }
        dbFeedSources.forEach((feed) => {
            const li = document.createElement('li');
            let displayName = feed.name || getFeedNameByUrl(feed.url);
            
            const detailsSpan = document.createElement('span');
            detailsSpan.classList.add('feed-details');
            detailsSpan.textContent = `${displayName} (URL: ${feed.url}, Interval: ${feed.fetch_interval_minutes}m)`;
            li.appendChild(detailsSpan);
            
            const controlsDiv = document.createElement('div');
            controlsDiv.classList.add('feed-controls');

            const editBtn = document.createElement('button');
            editBtn.textContent = 'Edit';
            editBtn.classList.add('edit-feed-btn'); 
            editBtn.onclick = () => promptEditFeed(feed);
            controlsDiv.appendChild(editBtn);

            const removeBtn = document.createElement('button');
            removeBtn.textContent = 'Remove';
            removeBtn.classList.add('remove-site-btn'); 
            removeBtn.onclick = () => deleteFeedSource(feed.id);
            controlsDiv.appendChild(removeBtn);
            
            li.appendChild(controlsDiv);
            rssFeedsListUI.appendChild(li);
        });
    }
    
    async function promptEditFeed(feed) {
        const newName = prompt("Enter new name for the feed (or leave blank to keep current):", feed.name || "");
        const newIntervalStr = prompt(`Enter new fetch interval in minutes for "${feed.name || feed.url}" (leave blank to keep ${feed.fetch_interval_minutes}m):`, feed.fetch_interval_minutes);

        const updatePayload = {};
        let changed = false;

        if (newName !== null && newName.trim() !== (feed.name || "")) { 
            updatePayload.name = newName.trim() === "" ? null : newName.trim(); 
            changed = true;
        } else if (newName !== null && newName.trim() === "" && feed.name !== null) { 
            updatePayload.name = null;
            changed = true;
        }

        if (newIntervalStr !== null && newIntervalStr.trim() !== "") {
            const newInterval = parseInt(newIntervalStr);
            if (!isNaN(newInterval) && newInterval >= 5 && newInterval !== feed.fetch_interval_minutes) { // Min interval 5
                updatePayload.fetch_interval_minutes = newInterval;
                changed = true;
            } else if (newIntervalStr.trim() !== "" && (isNaN(newInterval) || newInterval < 5)) {
                alert("Invalid interval. Please enter a positive number (minimum 5 minutes).");
                return;
            }
        }

        if (changed) {
            try {
                const response = await fetch(`/api/feeds/${feed.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updatePayload)
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({detail: `HTTP error ${response.status}`}));
                    throw new Error(errorData.detail || `Failed to update feed.`);
                }
                alert("Feed updated successfully!");
                await loadAndRenderDbFeeds(); 
            } catch (error) {
                console.error("Error updating feed:", error);
                alert(`Error updating feed: ${error.message}`);
            }
        } else {
            alert("No changes made to the feed.");
        }
    }

    if (addRssFeedForm) {
        addRssFeedForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const url = rssFeedUrlInput.value.trim();
            const name = rssFeedNameInput.value.trim();
            const intervalStr = rssFeedIntervalInput.value.trim();
            let fetch_interval_minutes = globalRssFetchInterval; 

            if (!url) { alert("Feed URL is required."); return; }
            if (intervalStr) {
                const parsedInterval = parseInt(intervalStr);
                if (isNaN(parsedInterval) || parsedInterval < 5) { // Min interval 5
                    alert("Invalid fetch interval. Please enter a positive number (minimum 5 minutes) or leave blank for default.");
                    return;
                }
                fetch_interval_minutes = parsedInterval;
            }

            try {
                const response = await fetch('/api/feeds', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, name: name || null, fetch_interval_minutes })
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({detail: `HTTP error ${response.status}`}));
                    throw new Error(errorData.detail || `Failed to add feed.`);
                }
                const newFeed = await response.json();
                await loadAndRenderDbFeeds(); 
                
                rssFeedUrlInput.value = '';
                rssFeedNameInput.value = '';
                rssFeedIntervalInput.value = '';
                alert(`Feed "${newFeed.name || newFeed.url}" added successfully!`);
            } catch (error) {
                console.error("Error adding feed:", error);
                alert(`Error adding feed: ${error.message}`);
            }
        });
    }

    async function deleteFeedSource(feedId) {
        if (!confirm(`Are you sure you want to remove feed ID ${feedId} and all its articles/summaries? This cannot be undone.`)) {
            return;
        }
        try {
            const response = await fetch(`/api/feeds/${feedId}`, { method: 'DELETE' });
            if (!response.ok) { 
                 if (response.status !== 204) {
                    const errorData = await response.json().catch(() => ({detail: `HTTP error ${response.status}`}));
                    throw new Error(errorData.detail || `Failed to delete feed.`);
                 }
            }
            alert("Feed deleted successfully!");
            await loadAndRenderDbFeeds(); 
            
            if (activeFeedFilterIds.includes(feedId)) {
                activeFeedFilterIds = []; 
                fetchAndDisplaySummaries(false, 1);
            }
        } catch (error) {
            console.error("Error deleting feed:", error);
            alert(`Error deleting feed: ${error.message}`);
        }
    }
    
    if (globalRssSettingsForm) {
        globalRssSettingsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newInterval = parseInt(rssFetchIntervalInput.value);
            if (!isNaN(newInterval) && newInterval >= 5) {
                globalRssFetchInterval = newInterval;
                updateSetupUI();
                alert(`Default RSS fetch interval preference updated to ${globalRssFetchInterval} minutes. Note: Backend scheduler might require restart or dynamic update for this to take full effect on its schedule.`);
            } else {
                alert("Please enter a valid interval (minimum 5 minutes).");
            }
        });
    }

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
                localStorage.setItem('newsChatApiEndpoint', newChatApiUrl); 
                CHAT_API_ENDPOINT_BASE = newChatApiUrl.startsWith('/api/chat-with-article') ? '/api' : newChatApiUrl.substring(0, newChatApiUrl.lastIndexOf('/')); 
                if (!CHAT_API_ENDPOINT_BASE) CHAT_API_ENDPOINT_BASE = '/api'; 
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
            if (newArticlesPerPage >= 1 && newArticlesPerPage <= 20) { 
                articlesPerPage = newArticlesPerPage; 
                localStorage.setItem('articlesPerPage', articlesPerPage.toString());
                updateSetupUI(); 
                alert('Content preferences saved! Articles per page set to ' + articlesPerPage);
                currentPage = 1; 
                fetchAndDisplaySummaries(false, 1); 
            } else { 
                alert('Please enter a number of articles per page between 1 and 20.'); 
            }
        });
    }


    // --- Feed Filter Button Management (Uses dbFeedSources) ---
    function renderFeedFilterButtons() { 
        if (!feedFilterControls) return;
        feedFilterControls.innerHTML = ''; 

        const allFeedsButton = document.createElement('button');
        allFeedsButton.textContent = 'All Feeds';
        allFeedsButton.onclick = () => {
            if (activeFeedFilterIds.length === 0) return; 
            activeFeedFilterIds = []; 
            updateFilterButtonStyles();
            fetchAndDisplaySummaries(false, 1); 
        };
        feedFilterControls.appendChild(allFeedsButton);
        
        dbFeedSources.forEach(feed => { 
            const feedButton = document.createElement('button');
            feedButton.textContent = getFeedNameById(feed.id); 
            feedButton.setAttribute('data-feedid', feed.id); 
            feedButton.onclick = () => {
                if (activeFeedFilterIds.length === 1 && activeFeedFilterIds[0] === feed.id) return; 
                
                activeFeedFilterIds = [feed.id]; 
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
            const feedIdAttr = button.getAttribute('data-feedid');
            if (activeFeedFilterIds.length === 0 && button.textContent === 'All Feeds') {
                button.classList.add('active');
            } else if (feedIdAttr && activeFeedFilterIds.includes(parseInt(feedIdAttr))) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    }

    // --- Fetching and Displaying News Summaries (Uses DB) ---
    async function fetchAndDisplaySummaries(forceBackendRssRefresh = false, page = 1) { 
        console.log(`SCRIPT.JS: fetchAndDisplaySummaries: Called. Page: ${page}, Active Filters: ${JSON.stringify(activeFeedFilterIds)}`);
        if (!resultsContainer || !loadingIndicator || !loadingText) {
            console.error("SCRIPT.JS: fetchAndDisplaySummaries: Essential DOM elements missing.");
            return;
        }
        
        currentPage = page; 
        let activeFeedNameDisplay = "All Feeds";
        if (activeFeedFilterIds.length > 0) {
            activeFeedNameDisplay = activeFeedFilterIds.map(id => getFeedNameById(id)).join(', ');
        }
        loadingText.textContent = `Fetching page ${currentPage} for ${activeFeedNameDisplay}...`;
        loadingIndicator.style.display = 'flex'; 
        if(resultsContainer) resultsContainer.innerHTML = ''; 
        if(page === 1) { 
            updatePaginationUI(0,0,0,0);
        }
        
        const payload = { 
            page: currentPage, 
            page_size: articlesPerPage, 
            feed_source_ids: activeFeedFilterIds.length > 0 ? activeFeedFilterIds : null, 
            summary_prompt: (currentSummaryPrompt !== defaultSummaryPrompt) ? currentSummaryPrompt : null, 
        };
        console.log("SCRIPT.JS: fetchAndDisplaySummaries: Sending payload:", JSON.stringify(payload));
        
        try {
            const response = await fetch(SUMMARIES_API_ENDPOINT, { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            });
            console.log("SCRIPT.JS: fetchAndDisplaySummaries: API response status:", response.status);
            if (!response.ok) { 
                const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` })); 
                console.error("SCRIPT.JS: fetchAndDisplaySummaries: API Error Data:", errorData);
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`); 
            }
            const data = await response.json(); 
            console.log("SCRIPT.JS: fetchAndDisplaySummaries: Received data:", data);
            displayResults(data.processed_articles_on_page); 
            totalArticlesAvailable = data.total_articles_available; 
            totalPages = data.total_pages;
            currentPage = data.requested_page; 
            updatePaginationUI(currentPage, totalPages, articlesPerPage, totalArticlesAvailable);

            if (dbFeedSources.length === 0 && data.processed_articles_on_page.length === 0) {
                 if(resultsContainer) resultsContainer.innerHTML = '<p>No RSS feeds configured in the database. Please add some in the Setup tab.</p>';
            } else if (data.processed_articles_on_page.length === 0 && totalArticlesAvailable === 0) {
                 if(resultsContainer) resultsContainer.innerHTML = `<p>No articles found for the current filter (${activeFeedNameDisplay}).</p>`;
            }

        } catch (error) { 
            console.error('SCRIPT.JS: Error fetching summaries:', error); 
            if(resultsContainer) resultsContainer.innerHTML = `<p class="error-message">Error fetching summaries: ${error.message}.</p>`; 
            updatePaginationUI(0,0,0,0); 
        }
        finally { 
            loadingIndicator.style.display = 'none'; 
            console.log("SCRIPT.JS: fetchAndDisplaySummaries: Finished.");
        }
    }

    if (refreshNewsBtn) { 
        refreshNewsBtn.addEventListener('click', async () => {
            if (!confirm("This will ask the backend to check all RSS feeds for new articles. Continue?")) return;
            
            loadingText.textContent = 'Requesting backend to refresh RSS feeds...';
            loadingIndicator.style.display = 'flex';
            try {
                const response = await fetch('/api/trigger-rss-refresh', { method: 'POST' });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({detail: `HTTP error ${response.status}`}));
                    throw new Error(errorData.detail || "Failed to trigger RSS refresh.");
                }
                const result = await response.json();
                alert(result.message || "RSS refresh initiated. New articles will appear after processing.");
                setTimeout(() => {
                    fetchAndDisplaySummaries(false, currentPage); 
                }, 3000); 
            } catch (error) {
                console.error("Error triggering RSS refresh:", error);
                alert(`Error: ${error.message}`);
            } finally {
                loadingIndicator.style.display = 'none';
            }
        });
    }
    
    // --- UI Update Functions (Pagination, Results Display) ---
    function updatePaginationUI(currentPg, totalPgs, pgSize, totalItems) { 
        const renderControls = (container) => {
            if (!container) return; 
            container.innerHTML = ''; 
            if (totalPgs <= 0) { // If no pages or only one page, don't show pagination
                 if (totalItems > 0 && totalPgs === 1) { // Show page info if only one page but has items
                    const pageInfo = document.createElement('span'); 
                    pageInfo.classList.add('page-info');
                    pageInfo.textContent = `Page ${currentPg} of ${totalPgs} (${totalItems} articles)`;
                    container.appendChild(pageInfo);
                 }
                return;
            }

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
        console.log("SCRIPT.JS: displayResults: Called with articles:", articles);
        if (!articles || articles.length === 0) {
            console.log("SCRIPT.JS: displayResults: No articles to display.");
            if (resultsContainer && currentPage === 1) { 
                 resultsContainer.innerHTML = '<p>No articles found for the current selection.</p>';
            }
            return;
        }
        if (!resultsContainer) {
            console.error("SCRIPT.JS: displayResults: resultsContainer is null!");
            return;
        }

        articles.forEach((article, index) => {
            const uniqueArticleCardId = `article-db-${article.id}`; 

            const articleCard = document.createElement('div'); articleCard.classList.add('article-card');
            articleCard.setAttribute('id', uniqueArticleCardId);
            
            const regenButton = document.createElement('button');
            regenButton.classList.add('regenerate-summary-btn');
            regenButton.title = "Regenerate Summary";
            regenButton.onclick = () => openRegenerateModal(article.id); 
            articleCard.appendChild(regenButton);

            const titleEl = document.createElement('h3'); titleEl.textContent = article.title || 'No Title Provided'; articleCard.appendChild(titleEl);
            const metaInfo = document.createElement('div'); metaInfo.classList.add('article-meta-info');
            if (article.publisher) { const p = document.createElement('span'); p.classList.add('article-publisher'); p.textContent = `Source: ${article.publisher}`; metaInfo.appendChild(p); }
            if (article.published_date) { const d = document.createElement('span'); d.classList.add('article-published-date'); try { d.textContent = `Published: ${new Date(article.published_date).toLocaleString(undefined, { year: 'numeric', month: 'long', day: 'numeric', hour:'numeric', minute:'numeric' })}`; } catch (e) { d.textContent = `Published: ${article.published_date}`; } metaInfo.appendChild(d); }
            if (metaInfo.hasChildNodes()) articleCard.appendChild(metaInfo);

            if (article.url) { const l = document.createElement('a'); l.href = article.url; l.textContent = 'Read Full Article'; l.classList.add('source-link'); l.target = '_blank'; l.rel = 'noopener noreferrer'; articleCard.appendChild(l); }
            
            const summaryP = document.createElement('p');
            summaryP.classList.add('summary');
            summaryP.setAttribute('id', `summary-text-${article.id}`); 
            summaryP.textContent = article.summary || "No summary available.";
            articleCard.appendChild(summaryP);
            
            if (article.error_message && !article.summary) { 
                const err = document.createElement('p'); 
                err.classList.add('error-message'); 
                err.textContent = `Note: ${article.error_message}`; 
                articleCard.appendChild(err); 
            }
            
            if (article.id && article.url && CHAT_API_ENDPOINT_BASE) { 
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
                chatInputEl.setAttribute('id', `chat-input-${uniqueArticleCardId}`); 
                chatInputGroupDiv.appendChild(chatInputEl);
                const chatButtonEl = document.createElement('button'); 
                chatButtonEl.textContent = 'Ask'; 
                chatButtonEl.classList.add('chat-ask-button'); 
                chatButtonEl.onclick = () => handleArticleChat(article.id, uniqueArticleCardId); 
                chatInputEl.addEventListener('keypress', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault(); 
                        handleArticleChat(article.id, uniqueArticleCardId);
                    }
                });
                chatInputGroupDiv.appendChild(chatButtonEl);
                chatSectionDiv.appendChild(chatInputGroupDiv); 
                const chatResponseAreaDiv = document.createElement('div'); 
                chatResponseAreaDiv.classList.add('chat-response'); 
                chatResponseAreaDiv.setAttribute('id', `chat-response-${uniqueArticleCardId}`);
                fetchChatHistory(article.id, chatResponseAreaDiv); 
                chatSectionDiv.appendChild(chatResponseAreaDiv);
                articleCard.appendChild(chatSectionDiv);
            }
            resultsContainer.appendChild(articleCard);
        });
        console.log("SCRIPT.JS: displayResults: Finished appending article cards.");
    }

    // --- Modal Handling for Regenerate Summary ---
    function openRegenerateModal(articleId) {
        if (!regenerateSummaryModal || !modalArticleIdInput || !modalSummaryPromptInput) return;
        modalArticleIdInput.value = articleId;
        modalSummaryPromptInput.value = currentSummaryPrompt || defaultSummaryPrompt; 
        regenerateSummaryModal.style.display = "block";
    }

    function closeRegenerateModal() {
        if (regenerateSummaryModal) regenerateSummaryModal.style.display = "none";
    }

    if (closeRegenerateModalBtn) {
        closeRegenerateModalBtn.onclick = closeRegenerateModal;
    }
    window.onclick = function(event) {
        if (event.target == regenerateSummaryModal) {
            closeRegenerateModal();
        }
    }

    if (modalUseDefaultPromptBtn) {
        modalUseDefaultPromptBtn.onclick = () => {
            if (modalSummaryPromptInput) modalSummaryPromptInput.value = defaultSummaryPrompt;
        };
    }

    if (regeneratePromptForm) {
        regeneratePromptForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const articleId = modalArticleIdInput.value;
            let customPrompt = modalSummaryPromptInput.value.trim();

            if (!customPrompt) { 
                customPrompt = defaultSummaryPrompt;
            } else if (!customPrompt.includes("{text}")) {
                alert("The custom prompt must include the placeholder {text} to insert the article content.");
                return;
            }
            
            const articleCardElement = document.getElementById(`article-db-${articleId}`);
            const summaryElement = document.getElementById(`summary-text-${articleId}`);
            const regenButton = articleCardElement ? articleCardElement.querySelector('.regenerate-summary-btn') : null;

            if (!summaryElement) {
                console.error("Could not find summary element for article ID:", articleId);
                closeRegenerateModal();
                return;
            }

            summaryElement.textContent = "Regenerating summary...";
            if (regenButton) regenButton.disabled = true; 

            try {
                const response = await fetch(`/api/articles/${articleId}/regenerate-summary`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ custom_prompt: customPrompt })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ detail: `HTTP error ${response.status}` }));
                    throw new Error(errorData.detail || "Failed to regenerate summary.");
                }
                const updatedArticle = await response.json();
                summaryElement.textContent = updatedArticle.summary || "Summary regenerated, but no content returned.";
                if (updatedArticle.error_message) {
                    summaryElement.textContent = `Error: ${updatedArticle.error_message}`;
                }
            } catch (error) {
                console.error("Error regenerating summary:", error);
                summaryElement.textContent = `Error: ${error.message}`;
                alert(`Failed to regenerate summary: ${error.message}`);
            } finally {
                if (regenButton) regenButton.disabled = false;
                closeRegenerateModal();
            }
        });
    }

    // --- Article Chat Handling (Uses article_id from DB) ---
    async function handleArticleChat(articleDbId, uniqueArticleCardId) { 
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
                article_id: articleDbId, 
                question: question,
                chat_prompt: (currentChatPrompt !== defaultChatPrompt) ? currentChatPrompt : null 
            };
            const response = await fetch(`${CHAT_API_ENDPOINT_BASE}/chat-with-article`, { 
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
            
            if (data.new_chat_history_item) {
                 const aDiv = document.createElement('div');
                 aDiv.classList.add('chat-history-a');
                 aDiv.textContent = `AI: ${answer}`;
                 if (data.error_message || answer.startsWith("Error:")) { 
                     aDiv.classList.add('error-message');
                     aDiv.textContent = `AI: ${data.error_message || answer}`; 
                 }
                 responseDiv.appendChild(aDiv);
            } else { 
                await fetchChatHistory(articleDbId, responseDiv); 
            }

        } catch (error) { 
            console.error('Error during article chat:', error); 
            const errorDiv = document.createElement('div');
            errorDiv.classList.add('chat-history-a', 'error-message');
            errorDiv.textContent = `AI Error: ${error.message}`;
            responseDiv.appendChild(errorDiv);
        } finally { 
            questionInput.disabled = false; 
            if(askButton) askButton.disabled = false;
            if (responseDiv.scrollHeight > responseDiv.clientHeight) responseDiv.scrollTop = responseDiv.scrollHeight;
            questionInput.focus(); 
        }
    }
    
    // --- Data Management (Setup Page) ---
    if (deleteOldDataBtn) {
        deleteOldDataBtn.addEventListener('click', async () => {
            const days = parseInt(daysOldInput.value);
            if (isNaN(days) || days <= 0) {
                alert("Please enter a valid positive number of days.");
                return;
            }

            if (!confirm(`Are you sure you want to delete all articles (and their summaries/chat history) older than ${days} days? This action cannot be undone.`)) {
                return;
            }

            if(deleteStatusMessage) deleteStatusMessage.textContent = "Deleting old data...";
            try {
                const response = await fetch(`/api/admin/cleanup-old-data?days_old=${days}`, {
                    method: 'DELETE'
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ detail: `HTTP error ${response.status}` }));
                    throw new Error(errorData.detail || "Failed to delete old data.");
                }
                const result = await response.json();
                alert(result.message || "Old data cleanup process completed.");
                if(deleteStatusMessage) deleteStatusMessage.textContent = result.message || "Cleanup complete.";
                fetchAndDisplaySummaries(false, 1); 
            } catch (error) {
                console.error("Error deleting old data:", error);
                alert(`Error: ${error.message}`);
                if(deleteStatusMessage) deleteStatusMessage.textContent = `Error: ${error.message}`;
            }
        });
    }

    // --- Navigation / Section Visibility ---
    function showSection(sectionId) { 
        console.log(`SCRIPT.JS: showSection called for: ${sectionId}`);
        if (!mainFeedSection || !setupSection || !navMainBtn || !navSetupBtn) {
            console.error("SCRIPT.JS: showSection: One or more navigation/section elements not found.");
            return;
        }
        mainFeedSection.classList.remove('active'); 
        setupSection.classList.remove('active');
        navMainBtn.classList.remove('active'); 
        navSetupBtn.classList.remove('active');

        const sectionToShow = document.getElementById(sectionId); 
        if (sectionToShow) {
            sectionToShow.classList.add('active');
            console.log(`SCRIPT.JS: Activated section: ${sectionId}`);
        } else {
            console.error(`SCRIPT.JS: Section with ID '${sectionId}' not found.`);
        }
        
        if (sectionId === 'main-feed-section') {
            navMainBtn.classList.add('active');
        } else if (sectionId === 'setup-section') {
            navSetupBtn.classList.add('active');
        }
    }

    // --- Initialize Event Listeners for Navigation ---
    if (navMainBtn) {
        console.log("SCRIPT.JS: Attaching listener to navMainBtn");
        navMainBtn.addEventListener('click', () => showSection('main-feed-section'));
    } else {
        console.error("SCRIPT.JS: navMainBtn not found!");
    }
    if (navSetupBtn) {
        console.log("SCRIPT.JS: Attaching listener to navSetupBtn");
        navSetupBtn.addEventListener('click', () => showSection('setup-section'));
    } else {
        console.error("SCRIPT.JS: navSetupBtn not found!");
    }
    
    // --- Final Initialization Call ---
    console.log("SCRIPT.JS: About to call initializeAppSettings...");
    await initializeAppSettings(); 
    console.log("SCRIPT.JS: initializeAppSettings call finished.");
});
