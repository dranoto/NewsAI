// script.js
document.addEventListener('DOMContentLoaded', async () => {
    // Main Feed Elements
    const resultsContainer = document.getElementById('results-container');
    const loadingIndicator = document.getElementById('loading-indicator');
    const loadingText = document.getElementById('loading-text');
    const refreshNewsBtn = document.getElementById('refresh-news-btn');
    const paginationControlsTop = document.getElementById('pagination-controls-top');
    const paginationControlsBottom = document.getElementById('pagination-controls-bottom');

    // Setup Section Elements
    const contentPrefsForm = document.getElementById('content-prefs-form');
    const numArticlesSetupInput = document.getElementById('num_articles_setup');
    const currentNumArticlesDisplay = document.getElementById('current-num-articles-display');

    const addRssFeedForm = document.getElementById('add-rss-feed-form');
    const rssFeedUrlInput = document.getElementById('rss-feed-url-input');
    const rssFeedsListUI = document.getElementById('rss-feeds-list');
    const clearRssFeedsBtn = document.getElementById('clear-rss-feeds-btn');

    const addSiteForm = document.getElementById('add-site-form');
    const siteDomainInput = document.getElementById('site-domain');
    const prioritizedSitesListUI = document.getElementById('prioritized-sites-list');
    const clearPrioritizedSitesButton = document.getElementById('clear-prioritized-sites');
    
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

    let rssFeedUrls = []; 
    let prioritizedWebsites = [];
    let SUMMARIES_API_ENDPOINT = '/api/get-news-summaries'; 
    let CHAT_API_ENDPOINT = '/api/chat-with-article';   
    let articlesPerPage = 6; 

    let currentPage = 1;
    let totalPages = 1;
    let totalArticlesAvailable = 0;

    // --- Chat History Management ---
    function getChatHistory(articleUrl) {
        return JSON.parse(localStorage.getItem(`chatHistory_${articleUrl}`)) || [];
    }

    function saveChatHistory(articleUrl, question, answer) {
        const history = getChatHistory(articleUrl);
        history.push({ question, answer });
        localStorage.setItem(`chatHistory_${articleUrl}`, JSON.stringify(history));
    }

    function renderChatHistory(responseDiv, articleUrl) {
        const history = getChatHistory(articleUrl);
        responseDiv.innerHTML = ''; 
        if (history.length === 0) {
            return; 
        }
        history.forEach(chat => {
            const qDiv = document.createElement('div');
            qDiv.classList.add('chat-history-q');
            qDiv.textContent = `You: ${chat.question}`;
            responseDiv.appendChild(qDiv);

            const aDiv = document.createElement('div');
            aDiv.classList.add('chat-history-a');
            aDiv.textContent = `AI: ${chat.answer}`;
            responseDiv.appendChild(aDiv);
        });
        responseDiv.scrollTop = responseDiv.scrollHeight; // Scroll to bottom after rendering history
    }

    async function fetchInitialConfig() {
        try {
            const response = await fetch('/api/initial-config'); 
            if (!response.ok) {
                console.warn('Failed to fetch initial config from backend, using local defaults/localStorage.');
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
        } catch (error) {
            console.error('Error fetching initial config:', error);
        }
    }

    async function initializeAppSettings() {
        await fetchInitialConfig(); 

        rssFeedUrls = JSON.parse(localStorage.getItem('rssFeedUrls')) || rssFeedUrls;
        prioritizedWebsites = JSON.parse(localStorage.getItem('prioritizedWebsites')) || [];
        SUMMARIES_API_ENDPOINT = localStorage.getItem('newsSummariesApiEndpoint') || SUMMARIES_API_ENDPOINT;
        CHAT_API_ENDPOINT = localStorage.getItem('newsChatApiEndpoint') || CHAT_API_ENDPOINT;
        articlesPerPage = parseInt(localStorage.getItem('articlesPerPage')) || articlesPerPage;

        if(currentApiUrlDisplay) currentApiUrlDisplay.textContent = SUMMARIES_API_ENDPOINT;
        if(apiUrlInput) apiUrlInput.value = SUMMARIES_API_ENDPOINT;
        if(currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = CHAT_API_ENDPOINT;
        if(chatApiUrlInput) chatApiUrlInput.value = CHAT_API_ENDPOINT;
        if(numArticlesSetupInput) numArticlesSetupInput.value = articlesPerPage;
        if(currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = articlesPerPage;

        renderRssFeeds();
        renderPrioritizedSites();
        showSection('main-feed-section');

        if (rssFeedUrls.length > 0) {
            fetchAndDisplaySummaries(true, 1); 
        } else {
            if(resultsContainer) resultsContainer.innerHTML = '<p>Please configure RSS feeds in the Setup tab to see news.</p>';
            updatePaginationUI(0,0,0,0);
        }
    }

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
    }
    function addRssFeed(url) {
        if (url && !rssFeedUrls.includes(url.trim())) {
            try { new URL(url.trim()); rssFeedUrls.push(url.trim()); localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls)); renderRssFeeds(); }
            catch (_) { alert("Please enter a valid URL for the RSS feed."); }
        } else if (rssFeedUrls.includes(url.trim())) { alert("This RSS feed URL is already in the list.");}
    }
    function removeRssFeed(index) {
        rssFeedUrls.splice(index, 1); localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls)); renderRssFeeds();
    }
    function clearAllRssFeeds() {
        rssFeedUrls = []; localStorage.removeItem('rssFeedUrls'); renderRssFeeds();
    }
    if (addRssFeedForm) addRssFeedForm.addEventListener('submit', (e) => { e.preventDefault(); addRssFeed(rssFeedUrlInput.value); rssFeedUrlInput.value = ''; });
    if (clearRssFeedsBtn) clearRssFeedsBtn.addEventListener('click', clearAllRssFeeds);

    function renderPrioritizedSites() {
        if (!prioritizedSitesListUI) return;
        prioritizedSitesListUI.innerHTML = '';
        prioritizedWebsites.forEach((siteKey, index) => {
            const li = document.createElement('li');
            li.textContent = siteKey;
            const removeBtn = document.createElement('button');
            removeBtn.textContent = 'Remove';
            removeBtn.classList.add('remove-site-btn');
            removeBtn.onclick = () => removePrioritizedSite(index);
            li.appendChild(removeBtn);
            prioritizedSitesListUI.appendChild(li);
        });
    }
    function addPrioritizedSite(siteKey) {
        if (siteKey && !prioritizedWebsites.includes(siteKey.trim().toLowerCase())) {
            prioritizedWebsites.push(siteKey.trim().toLowerCase()); localStorage.setItem('prioritizedWebsites', JSON.stringify(prioritizedWebsites)); renderPrioritizedSites();
        }
    }
    function removePrioritizedSite(index) {
        prioritizedWebsites.splice(index, 1); localStorage.setItem('prioritizedWebsites', JSON.stringify(prioritizedWebsites)); renderPrioritizedSites();
    }
    function clearAllPrioritizedSites() {
        prioritizedWebsites = []; localStorage.removeItem('prioritizedWebsites'); renderPrioritizedSites();
    }
    if (addSiteForm) addSiteForm.addEventListener('submit', (e) => { e.preventDefault(); addPrioritizedSite(siteDomainInput.value); siteDomainInput.value = ''; });
    if (clearPrioritizedSitesButton) clearPrioritizedSitesButton.addEventListener('click', clearAllPrioritizedSites);
    
    if(apiEndpointForm) {
        apiEndpointForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newSummariesApiUrl = apiUrlInput.value.trim();
            const newChatApiUrl = chatApiUrlInput.value.trim();
            let updated = false;
            if (newSummariesApiUrl) {
                SUMMARIES_API_ENDPOINT = newSummariesApiUrl; localStorage.setItem('newsSummariesApiEndpoint', SUMMARIES_API_ENDPOINT);
                if(currentApiUrlDisplay) currentApiUrlDisplay.textContent = SUMMARIES_API_ENDPOINT; updated = true;
            }
            if (newChatApiUrl) {
                CHAT_API_ENDPOINT = newChatApiUrl; localStorage.setItem('newsChatApiEndpoint', CHAT_API_ENDPOINT);
                if(currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = CHAT_API_ENDPOINT; updated = true;
            }
            if(updated) alert('API Endpoints updated!');
        });
    }

    if (contentPrefsForm) {
        contentPrefsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newArticlesPerPage = parseInt(numArticlesSetupInput.value);
            if (newArticlesPerPage >= 1 && newArticlesPerPage <= 12) {
                articlesPerPage = newArticlesPerPage; localStorage.setItem('articlesPerPage', articlesPerPage.toString());
                if(currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = articlesPerPage;
                alert('Content preferences saved! Articles per page set to ' + articlesPerPage);
                currentPage = 1; fetchAndDisplaySummaries(true, 1);
            } else { alert('Please enter a number of articles per page between 1 and 12.'); }
        });
    }

    async function fetchAndDisplaySummaries(forceRssRefresh = false, page = 1) {
        if (!resultsContainer || !loadingIndicator || !loadingText) return;
        if (rssFeedUrls.length === 0) { 
             if(resultsContainer) resultsContainer.innerHTML = '<p>No RSS feeds configured. Please add some in the Setup tab and click "Refresh News Feed".</p>';
             updatePaginationUI(0, 0, 0, 0); return;
        }
        currentPage = page; 
        loadingText.textContent = `Fetching page ${currentPage}...`;
        loadingIndicator.style.display = 'flex'; 
        if(page === 1 && forceRssRefresh) { 
            updatePaginationUI(0,0,0,0);
        }

        const payload = { page: currentPage, page_size: articlesPerPage, prioritized_sites: prioritizedWebsites, rss_feed_urls: rssFeedUrls, force_refresh_rss: forceRssRefresh };
        try {
            const response = await fetch(SUMMARIES_API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (!response.ok) { const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` })); throw new Error(errorData.detail || `HTTP error! status: ${response.status}`); }
            const data = await response.json(); 
            displayResults(data.processed_articles_on_page); 
            totalArticlesAvailable = data.total_articles_available; totalPages = data.total_pages;
            updatePaginationUI(currentPage, totalPages, articlesPerPage, totalArticlesAvailable);
        } catch (error) { 
            console.error('Error fetching summaries:', error); 
            if(resultsContainer) resultsContainer.innerHTML = `<p class="error-message">Error fetching summaries: ${error.message}.</p>`; 
            updatePaginationUI(0,0,0,0); 
        }
        finally { loadingIndicator.style.display = 'none'; }
    }

    if (refreshNewsBtn) {
        refreshNewsBtn.addEventListener('click', () => fetchAndDisplaySummaries(true, 1));
    }
    
    function updatePaginationUI(currentPg, totalPgs, pgSize, totalItems) {
        const renderControls = (container) => {
            if (!container) return; container.innerHTML = ''; if (totalPgs <= 0) return;
            const prevButton = document.createElement('button'); prevButton.textContent = '‹ Previous';
            prevButton.disabled = currentPg <= 1; prevButton.onclick = () => fetchAndDisplaySummaries(false, currentPg - 1);
            container.appendChild(prevButton);
            const pageInfo = document.createElement('span'); pageInfo.classList.add('page-info');
            pageInfo.textContent = `Page ${currentPg} of ${totalPgs} (${totalItems} articles total)`;
            container.appendChild(pageInfo);
            const nextButton = document.createElement('button'); nextButton.textContent = 'Next ›';
            nextButton.disabled = currentPg >= totalPgs; nextButton.onclick = () => fetchAndDisplaySummaries(false, currentPg + 1);
            container.appendChild(nextButton);
        };
        renderControls(paginationControlsTop); renderControls(paginationControlsBottom);
    }

    function displayResults(articles) {
        resultsContainer.innerHTML = ''; // Clear previous page's results
        if (!articles || articles.length === 0) {
            if (currentPage === 1) { resultsContainer.innerHTML = '<p>No summaries found from the configured RSS feeds for this page.</p>';}
            else { resultsContainer.innerHTML = '<p>No more summaries available.</p>';}
            return;
        }
        articles.forEach((article, index) => {
            const uniqueArticleId = `article-${currentPage}-${index}`; 

            const articleCard = document.createElement('div'); articleCard.classList.add('article-card');
            articleCard.setAttribute('id', uniqueArticleId);
            
            const titleEl = document.createElement('h3'); titleEl.textContent = article.title || 'No Title Provided'; articleCard.appendChild(titleEl);
            const metaInfo = document.createElement('div'); metaInfo.classList.add('article-meta-info');
            if (article.publisher) { const p = document.createElement('span'); p.classList.add('article-publisher'); p.textContent = `Source: ${article.publisher}`; metaInfo.appendChild(p); }
            if (article.published_date) { const d = document.createElement('span'); d.classList.add('article-published-date'); try { d.textContent = `Published: ${new Date(article.published_date).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}`; } catch (e) { d.textContent = `Published: ${article.published_date}`; } metaInfo.appendChild(d); }
            if (metaInfo.children.length > 1 && metaInfo.children[0].style) { metaInfo.children[0].style.marginRight = "15px"; }
            if (metaInfo.hasChildNodes()) articleCard.appendChild(metaInfo);
            if (article.url) { const l = document.createElement('a'); l.href = article.url; l.textContent = 'Read Full Article'; l.classList.add('source-link'); l.target = '_blank'; articleCard.appendChild(l); }
            if (article.summary) { const s = document.createElement('p'); s.classList.add('summary'); s.textContent = article.summary; articleCard.appendChild(s); }
            if (article.error_message) { const err = document.createElement('p'); err.classList.add('error-message'); err.textContent = `Note: ${article.error_message}`; articleCard.appendChild(err); }
            
            if (article.url && !article.error_message) {
                const chatSectionDiv = document.createElement('div'); // Use full name
                chatSectionDiv.classList.add('chat-section');
                const chatTitleEl = document.createElement('h4'); // Use full name
                chatTitleEl.textContent = 'Ask about this article:'; 
                chatSectionDiv.appendChild(chatTitleEl);
                const chatInputGroupDiv = document.createElement('div'); // Use full name
                chatInputGroupDiv.classList.add('chat-input-group');
                const chatInputEl = document.createElement('input'); // Use full name
                chatInputEl.setAttribute('type', 'text'); 
                chatInputEl.setAttribute('placeholder', 'Your question...'); 
                chatInputEl.classList.add('chat-question-input'); 
                chatInputEl.setAttribute('id', `chat-input-${uniqueArticleId}`); 
                chatInputGroupDiv.appendChild(chatInputEl);
                const chatButtonEl = document.createElement('button'); // Use full name
                chatButtonEl.textContent = 'Ask'; 
                chatButtonEl.classList.add('chat-ask-button'); 
                chatButtonEl.onclick = () => handleArticleChat(article.url, uniqueArticleId); 
                chatInputGroupDiv.appendChild(chatButtonEl);
                chatSectionDiv.appendChild(chatInputGroupDiv); 
                const chatResponseAreaDiv = document.createElement('div'); // Use full name
                chatResponseAreaDiv.classList.add('chat-response'); 
                chatResponseAreaDiv.setAttribute('id', `chat-response-${uniqueArticleId}`);
                renderChatHistory(chatResponseAreaDiv, article.url); 
                chatSectionDiv.appendChild(chatResponseAreaDiv);
                articleCard.appendChild(chatSectionDiv);
            }
            resultsContainer.appendChild(articleCard);
        });
    }

    async function handleArticleChat(articleUrl, uniqueArticleCardId) {
        const questionInput = document.getElementById(`chat-input-${uniqueArticleCardId}`); 
        const responseDiv = document.getElementById(`chat-response-${uniqueArticleCardId}`);
        const question = questionInput.value.trim(); 
        if (!question) { alert('Please enter a question.'); return; }
        
        const qDiv = document.createElement('div');
        qDiv.classList.add('chat-history-q');
        qDiv.textContent = `You: ${question}`;
        responseDiv.appendChild(qDiv);
        responseDiv.scrollTop = responseDiv.scrollHeight;

        const loadingChatP = document.createElement('p');
        loadingChatP.classList.add('chat-loading');
        loadingChatP.textContent = 'AI is thinking...';
        responseDiv.appendChild(loadingChatP);
        responseDiv.scrollTop = responseDiv.scrollHeight;

        questionInput.value = ''; 
        questionInput.disabled = true; 
        const askButton = questionInput.nextElementSibling; 
        if(askButton) askButton.disabled = true;

        try {
            const payload = { article_url: articleUrl, question: question };
            const response = await fetch(CHAT_API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            
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
            responseDiv.appendChild(aDiv);

        } catch (error) { 
            console.error('Error during article chat:', error); 
            const errorDiv = document.createElement('div');
            errorDiv.classList.add('chat-history-a', 'error-message');
            errorDiv.textContent = `AI Error: ${error.message}`;
            responseDiv.appendChild(errorDiv);
        } finally { 
            questionInput.disabled = false; 
            if(askButton) askButton.disabled = false;
            responseDiv.scrollTop = responseDiv.scrollHeight; 
        }
    }

    function showSection(sectionId) {
        if (mainFeedSection) mainFeedSection.classList.remove('active'); 
        if (setupSection) setupSection.classList.remove('active');
        if (navMainBtn) navMainBtn.classList.remove('active'); 
        if (navSetupBtn) navSetupBtn.classList.remove('active');
        const sectionToShow = document.getElementById(sectionId); 
        if (sectionToShow) sectionToShow.classList.add('active');
        if (sectionId === 'main-feed-section' && navMainBtn) navMainBtn.classList.add('active');
        else if (sectionId === 'setup-section' && navSetupBtn) navSetupBtn.classList.add('active');
    }
    if (navMainBtn && navSetupBtn) {
        navMainBtn.addEventListener('click', () => showSection('main-feed-section'));
        navSetupBtn.addEventListener('click', () => showSection('setup-section'));
    }
    
    await initializeAppSettings();
});
// script.js
document.addEventListener('DOMContentLoaded', async () => {
    // Main Feed Elements
    const resultsContainer = document.getElementById('results-container');
    const loadingIndicator = document.getElementById('loading-indicator');
    const loadingText = document.getElementById('loading-text');
    const refreshNewsBtn = document.getElementById('refresh-news-btn');
    const paginationControlsTop = document.getElementById('pagination-controls-top');
    const paginationControlsBottom = document.getElementById('pagination-controls-bottom');

    // Setup Section Elements
    const contentPrefsForm = document.getElementById('content-prefs-form');
    const numArticlesSetupInput = document.getElementById('num_articles_setup');
    const currentNumArticlesDisplay = document.getElementById('current-num-articles-display');

    const addRssFeedForm = document.getElementById('add-rss-feed-form');
    const rssFeedUrlInput = document.getElementById('rss-feed-url-input');
    const rssFeedsListUI = document.getElementById('rss-feeds-list');
    const clearRssFeedsBtn = document.getElementById('clear-rss-feeds-btn');

    const addSiteForm = document.getElementById('add-site-form');
    const siteDomainInput = document.getElementById('site-domain');
    const prioritizedSitesListUI = document.getElementById('prioritized-sites-list');
    const clearPrioritizedSitesButton = document.getElementById('clear-prioritized-sites');
    
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

    let rssFeedUrls = []; 
    let prioritizedWebsites = [];
    let SUMMARIES_API_ENDPOINT = '/api/get-news-summaries'; 
    let CHAT_API_ENDPOINT = '/api/chat-with-article';   
    let articlesPerPage = 6; 

    let currentPage = 1;
    let totalPages = 1;
    let totalArticlesAvailable = 0;

    // --- Chat History Management ---
    function getChatHistory(articleUrl) {
        return JSON.parse(localStorage.getItem(`chatHistory_${articleUrl}`)) || [];
    }

    function saveChatHistory(articleUrl, question, answer) {
        const history = getChatHistory(articleUrl);
        history.push({ question, answer });
        localStorage.setItem(`chatHistory_${articleUrl}`, JSON.stringify(history));
    }

    function renderChatHistory(responseDiv, articleUrl) {
        const history = getChatHistory(articleUrl);
        responseDiv.innerHTML = ''; 
        if (history.length === 0) {
            return; 
        }
        history.forEach(chat => {
            const qDiv = document.createElement('div');
            qDiv.classList.add('chat-history-q');
            qDiv.textContent = `You: ${chat.question}`;
            responseDiv.appendChild(qDiv);

            const aDiv = document.createElement('div');
            aDiv.classList.add('chat-history-a');
            aDiv.textContent = `AI: ${chat.answer}`;
            responseDiv.appendChild(aDiv);
        });
        responseDiv.scrollTop = responseDiv.scrollHeight; // Scroll to bottom after rendering history
    }

    async function fetchInitialConfig() {
        try {
            const response = await fetch('/api/initial-config'); 
            if (!response.ok) {
                console.warn('Failed to fetch initial config from backend, using local defaults/localStorage.');
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
        } catch (error) {
            console.error('Error fetching initial config:', error);
        }
    }

    async function initializeAppSettings() {
        await fetchInitialConfig(); 

        rssFeedUrls = JSON.parse(localStorage.getItem('rssFeedUrls')) || rssFeedUrls;
        prioritizedWebsites = JSON.parse(localStorage.getItem('prioritizedWebsites')) || [];
        SUMMARIES_API_ENDPOINT = localStorage.getItem('newsSummariesApiEndpoint') || SUMMARIES_API_ENDPOINT;
        CHAT_API_ENDPOINT = localStorage.getItem('newsChatApiEndpoint') || CHAT_API_ENDPOINT;
        articlesPerPage = parseInt(localStorage.getItem('articlesPerPage')) || articlesPerPage;

        if(currentApiUrlDisplay) currentApiUrlDisplay.textContent = SUMMARIES_API_ENDPOINT;
        if(apiUrlInput) apiUrlInput.value = SUMMARIES_API_ENDPOINT;
        if(currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = CHAT_API_ENDPOINT;
        if(chatApiUrlInput) chatApiUrlInput.value = CHAT_API_ENDPOINT;
        if(numArticlesSetupInput) numArticlesSetupInput.value = articlesPerPage;
        if(currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = articlesPerPage;

        renderRssFeeds();
        renderPrioritizedSites();
        showSection('main-feed-section');

        if (rssFeedUrls.length > 0) {
            fetchAndDisplaySummaries(true, 1); 
        } else {
            if(resultsContainer) resultsContainer.innerHTML = '<p>Please configure RSS feeds in the Setup tab to see news.</p>';
            updatePaginationUI(0,0,0,0);
        }
    }

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
    }
    function addRssFeed(url) {
        if (url && !rssFeedUrls.includes(url.trim())) {
            try { new URL(url.trim()); rssFeedUrls.push(url.trim()); localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls)); renderRssFeeds(); }
            catch (_) { alert("Please enter a valid URL for the RSS feed."); }
        } else if (rssFeedUrls.includes(url.trim())) { alert("This RSS feed URL is already in the list.");}
    }
    function removeRssFeed(index) {
        rssFeedUrls.splice(index, 1); localStorage.setItem('rssFeedUrls', JSON.stringify(rssFeedUrls)); renderRssFeeds();
    }
    function clearAllRssFeeds() {
        rssFeedUrls = []; localStorage.removeItem('rssFeedUrls'); renderRssFeeds();
    }
    if (addRssFeedForm) addRssFeedForm.addEventListener('submit', (e) => { e.preventDefault(); addRssFeed(rssFeedUrlInput.value); rssFeedUrlInput.value = ''; });
    if (clearRssFeedsBtn) clearRssFeedsBtn.addEventListener('click', clearAllRssFeeds);

    function renderPrioritizedSites() {
        if (!prioritizedSitesListUI) return;
        prioritizedSitesListUI.innerHTML = '';
        prioritizedWebsites.forEach((siteKey, index) => {
            const li = document.createElement('li');
            li.textContent = siteKey;
            const removeBtn = document.createElement('button');
            removeBtn.textContent = 'Remove';
            removeBtn.classList.add('remove-site-btn');
            removeBtn.onclick = () => removePrioritizedSite(index);
            li.appendChild(removeBtn);
            prioritizedSitesListUI.appendChild(li);
        });
    }
    function addPrioritizedSite(siteKey) {
        if (siteKey && !prioritizedWebsites.includes(siteKey.trim().toLowerCase())) {
            prioritizedWebsites.push(siteKey.trim().toLowerCase()); localStorage.setItem('prioritizedWebsites', JSON.stringify(prioritizedWebsites)); renderPrioritizedSites();
        }
    }
    function removePrioritizedSite(index) {
        prioritizedWebsites.splice(index, 1); localStorage.setItem('prioritizedWebsites', JSON.stringify(prioritizedWebsites)); renderPrioritizedSites();
    }
    function clearAllPrioritizedSites() {
        prioritizedWebsites = []; localStorage.removeItem('prioritizedWebsites'); renderPrioritizedSites();
    }
    if (addSiteForm) addSiteForm.addEventListener('submit', (e) => { e.preventDefault(); addPrioritizedSite(siteDomainInput.value); siteDomainInput.value = ''; });
    if (clearPrioritizedSitesButton) clearPrioritizedSitesButton.addEventListener('click', clearAllPrioritizedSites);
    
    if(apiEndpointForm) {
        apiEndpointForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newSummariesApiUrl = apiUrlInput.value.trim();
            const newChatApiUrl = chatApiUrlInput.value.trim();
            let updated = false;
            if (newSummariesApiUrl) {
                SUMMARIES_API_ENDPOINT = newSummariesApiUrl; localStorage.setItem('newsSummariesApiEndpoint', SUMMARIES_API_ENDPOINT);
                if(currentApiUrlDisplay) currentApiUrlDisplay.textContent = SUMMARIES_API_ENDPOINT; updated = true;
            }
            if (newChatApiUrl) {
                CHAT_API_ENDPOINT = newChatApiUrl; localStorage.setItem('newsChatApiEndpoint', CHAT_API_ENDPOINT);
                if(currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = CHAT_API_ENDPOINT; updated = true;
            }
            if(updated) alert('API Endpoints updated!');
        });
    }

    if (contentPrefsForm) {
        contentPrefsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newArticlesPerPage = parseInt(numArticlesSetupInput.value);
            if (newArticlesPerPage >= 1 && newArticlesPerPage <= 12) {
                articlesPerPage = newArticlesPerPage; localStorage.setItem('articlesPerPage', articlesPerPage.toString());
                if(currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = articlesPerPage;
                alert('Content preferences saved! Articles per page set to ' + articlesPerPage);
                currentPage = 1; fetchAndDisplaySummaries(true, 1);
            } else { alert('Please enter a number of articles per page between 1 and 12.'); }
        });
    }

    async function fetchAndDisplaySummaries(forceRssRefresh = false, page = 1) {
        if (!resultsContainer || !loadingIndicator || !loadingText) return;
        if (rssFeedUrls.length === 0) { 
             if(resultsContainer) resultsContainer.innerHTML = '<p>No RSS feeds configured. Please add some in the Setup tab and click "Refresh News Feed".</p>';
             updatePaginationUI(0, 0, 0, 0); return;
        }
        currentPage = page; 
        loadingText.textContent = `Fetching page ${currentPage}...`;
        loadingIndicator.style.display = 'flex'; 
        if(page === 1 && forceRssRefresh) { 
            updatePaginationUI(0,0,0,0);
        }

        const payload = { page: currentPage, page_size: articlesPerPage, prioritized_sites: prioritizedWebsites, rss_feed_urls: rssFeedUrls, force_refresh_rss: forceRssRefresh };
        try {
            const response = await fetch(SUMMARIES_API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (!response.ok) { const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` })); throw new Error(errorData.detail || `HTTP error! status: ${response.status}`); }
            const data = await response.json(); 
            displayResults(data.processed_articles_on_page); 
            totalArticlesAvailable = data.total_articles_available; totalPages = data.total_pages;
            updatePaginationUI(currentPage, totalPages, articlesPerPage, totalArticlesAvailable);
        } catch (error) { 
            console.error('Error fetching summaries:', error); 
            if(resultsContainer) resultsContainer.innerHTML = `<p class="error-message">Error fetching summaries: ${error.message}.</p>`; 
            updatePaginationUI(0,0,0,0); 
        }
        finally { loadingIndicator.style.display = 'none'; }
    }

    if (refreshNewsBtn) {
        refreshNewsBtn.addEventListener('click', () => fetchAndDisplaySummaries(true, 1));
    }
    
    function updatePaginationUI(currentPg, totalPgs, pgSize, totalItems) {
        const renderControls = (container) => {
            if (!container) return; container.innerHTML = ''; if (totalPgs <= 0) return;
            const prevButton = document.createElement('button'); prevButton.textContent = '‹ Previous';
            prevButton.disabled = currentPg <= 1; prevButton.onclick = () => fetchAndDisplaySummaries(false, currentPg - 1);
            container.appendChild(prevButton);
            const pageInfo = document.createElement('span'); pageInfo.classList.add('page-info');
            pageInfo.textContent = `Page ${currentPg} of ${totalPgs} (${totalItems} articles total)`;
            container.appendChild(pageInfo);
            const nextButton = document.createElement('button'); nextButton.textContent = 'Next ›';
            nextButton.disabled = currentPg >= totalPgs; nextButton.onclick = () => fetchAndDisplaySummaries(false, currentPg + 1);
            container.appendChild(nextButton);
        };
        renderControls(paginationControlsTop); renderControls(paginationControlsBottom);
    }

    function displayResults(articles) {
        resultsContainer.innerHTML = ''; // Clear previous page's results
        if (!articles || articles.length === 0) {
            if (currentPage === 1) { resultsContainer.innerHTML = '<p>No summaries found from the configured RSS feeds for this page.</p>';}
            else { resultsContainer.innerHTML = '<p>No more summaries available.</p>';}
            return;
        }
        articles.forEach((article, index) => {
            const uniqueArticleId = `article-${currentPage}-${index}`; 

            const articleCard = document.createElement('div'); articleCard.classList.add('article-card');
            articleCard.setAttribute('id', uniqueArticleId);
            
            const titleEl = document.createElement('h3'); titleEl.textContent = article.title || 'No Title Provided'; articleCard.appendChild(titleEl);
            const metaInfo = document.createElement('div'); metaInfo.classList.add('article-meta-info');
            if (article.publisher) { const p = document.createElement('span'); p.classList.add('article-publisher'); p.textContent = `Source: ${article.publisher}`; metaInfo.appendChild(p); }
            if (article.published_date) { const d = document.createElement('span'); d.classList.add('article-published-date'); try { d.textContent = `Published: ${new Date(article.published_date).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}`; } catch (e) { d.textContent = `Published: ${article.published_date}`; } metaInfo.appendChild(d); }
            if (metaInfo.children.length > 1 && metaInfo.children[0].style) { metaInfo.children[0].style.marginRight = "15px"; }
            if (metaInfo.hasChildNodes()) articleCard.appendChild(metaInfo);
            if (article.url) { const l = document.createElement('a'); l.href = article.url; l.textContent = 'Read Full Article'; l.classList.add('source-link'); l.target = '_blank'; articleCard.appendChild(l); }
            if (article.summary) { const s = document.createElement('p'); s.classList.add('summary'); s.textContent = article.summary; articleCard.appendChild(s); }
            if (article.error_message) { const err = document.createElement('p'); err.classList.add('error-message'); err.textContent = `Note: ${article.error_message}`; articleCard.appendChild(err); }
            
            if (article.url && !article.error_message) {
                const chatSectionDiv = document.createElement('div'); // Use full name
                chatSectionDiv.classList.add('chat-section');
                const chatTitleEl = document.createElement('h4'); // Use full name
                chatTitleEl.textContent = 'Ask about this article:'; 
                chatSectionDiv.appendChild(chatTitleEl);
                const chatInputGroupDiv = document.createElement('div'); // Use full name
                chatInputGroupDiv.classList.add('chat-input-group');
                const chatInputEl = document.createElement('input'); // Use full name
                chatInputEl.setAttribute('type', 'text'); 
                chatInputEl.setAttribute('placeholder', 'Your question...'); 
                chatInputEl.classList.add('chat-question-input'); 
                chatInputEl.setAttribute('id', `chat-input-${uniqueArticleId}`); 
                chatInputGroupDiv.appendChild(chatInputEl);
                const chatButtonEl = document.createElement('button'); // Use full name
                chatButtonEl.textContent = 'Ask'; 
                chatButtonEl.classList.add('chat-ask-button'); 
                chatButtonEl.onclick = () => handleArticleChat(article.url, uniqueArticleId); 
                chatInputGroupDiv.appendChild(chatButtonEl);
                chatSectionDiv.appendChild(chatInputGroupDiv); 
                const chatResponseAreaDiv = document.createElement('div'); // Use full name
                chatResponseAreaDiv.classList.add('chat-response'); 
                chatResponseAreaDiv.setAttribute('id', `chat-response-${uniqueArticleId}`);
                renderChatHistory(chatResponseAreaDiv, article.url); 
                chatSectionDiv.appendChild(chatResponseAreaDiv);
                articleCard.appendChild(chatSectionDiv);
            }
            resultsContainer.appendChild(articleCard);
        });
    }

    async function handleArticleChat(articleUrl, uniqueArticleCardId) {
        const questionInput = document.getElementById(`chat-input-${uniqueArticleCardId}`); 
        const responseDiv = document.getElementById(`chat-response-${uniqueArticleCardId}`);
        const question = questionInput.value.trim(); 
        if (!question) { alert('Please enter a question.'); return; }
        
        const qDiv = document.createElement('div');
        qDiv.classList.add('chat-history-q');
        qDiv.textContent = `You: ${question}`;
        responseDiv.appendChild(qDiv);
        responseDiv.scrollTop = responseDiv.scrollHeight;

        const loadingChatP = document.createElement('p');
        loadingChatP.classList.add('chat-loading');
        loadingChatP.textContent = 'AI is thinking...';
        responseDiv.appendChild(loadingChatP);
        responseDiv.scrollTop = responseDiv.scrollHeight;

        questionInput.value = ''; 
        questionInput.disabled = true; 
        const askButton = questionInput.nextElementSibling; 
        if(askButton) askButton.disabled = true;

        try {
            const payload = { article_url: articleUrl, question: question };
            const response = await fetch(CHAT_API_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            
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
            responseDiv.appendChild(aDiv);

        } catch (error) { 
            console.error('Error during article chat:', error); 
            const errorDiv = document.createElement('div');
            errorDiv.classList.add('chat-history-a', 'error-message');
            errorDiv.textContent = `AI Error: ${error.message}`;
            responseDiv.appendChild(errorDiv);
        } finally { 
            questionInput.disabled = false; 
            if(askButton) askButton.disabled = false;
            responseDiv.scrollTop = responseDiv.scrollHeight; 
        }
    }

    function showSection(sectionId) {
        if (mainFeedSection) mainFeedSection.classList.remove('active'); 
        if (setupSection) setupSection.classList.remove('active');
        if (navMainBtn) navMainBtn.classList.remove('active'); 
        if (navSetupBtn) navSetupBtn.classList.remove('active');
        const sectionToShow = document.getElementById(sectionId); 
        if (sectionToShow) sectionToShow.classList.add('active');
        if (sectionId === 'main-feed-section' && navMainBtn) navMainBtn.classList.add('active');
        else if (sectionId === 'setup-section' && navSetupBtn) navSetupBtn.classList.add('active');
    }
    if (navMainBtn && navSetupBtn) {
        navMainBtn.addEventListener('click', () => showSection('main-feed-section'));
        navSetupBtn.addEventListener('click', () => showSection('setup-section'));
    }
    
    await initializeAppSettings();
});
