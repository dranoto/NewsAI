// frontend/script.js (Main Orchestrator)
import * as state from './js/state.js';
import * as apiService from './js/apiService.js';
import * as configManager from './js/configManager.js';
import * as uiManager from './js/uiManager.js';
import * as chatHandler from './js/chatHandler.js';
import * as feedHandler from './js/feedHandler.js';

/**
 * Main script for the NewsAI frontend.
 * Orchestrates all modules and handles core application logic.
 */

// --- DOM Element References (for elements directly handled by this main script) ---
let refreshNewsBtn, keywordSearchInput, keywordSearchBtn,
    deleteOldDataBtn, daysOldInput, deleteStatusMessage,
    regeneratePromptForm;

// --- Polling Configuration ---
const POLLING_INTERVAL_MS = 120000; // Check for new articles every 2 minutes (120,000 ms)
let pollingIntervalId = null;

// --- Main Application Logic ---

async function fetchAndDisplaySummaries(forceBackendRssRefresh = false, page = state.currentPage, keyword = state.currentKeywordSearch, isPollRefresh = false) {
    console.log(`MainScript: fetchAndDisplaySummaries called. Page: ${page}, Keyword: ${keyword}, IsPoll: ${isPollRefresh}, FeedFilters: ${JSON.stringify(state.activeFeedFilterIds)}, TagFilters: ${JSON.stringify(state.activeTagFilterIds.map(t=>t.id))}`);
    
    if (page === 1) { 
        state.setCurrentPage(1); 
    }
    state.setIsLoadingMoreArticles(true);

    const loadingMessageParts = [];
    if (state.activeFeedFilterIds.length > 0) {
        const feedNames = state.activeFeedFilterIds.map(id => {
            const feed = state.dbFeedSources.find(f => f.id === id);
            return feed ? (feed.name || feed.url.split('/')[2]?.replace(/^www\./, '')) : `ID ${id}`;
        }).join(', ');
        loadingMessageParts.push(`Feeds: ${feedNames}`);
    }
    if (state.activeTagFilterIds.length > 0) {
        loadingMessageParts.push(`Tags: ${state.activeTagFilterIds.map(t => t.name).join(', ')}`);
    }
    if (keyword) {
        loadingMessageParts.push(`Keyword: "${keyword}"`);
    }
    const activeFilterDisplay = loadingMessageParts.length > 0 ? loadingMessageParts.join(' & ') : "All Articles";
    
    if (page === 1 && !isPollRefresh) { 
        uiManager.showLoadingIndicator(true, `Fetching page ${state.currentPage} for ${activeFilterDisplay}...`);
    } else if (page > 1) {
        uiManager.showInfiniteScrollLoadingIndicator(true);
    }

    const payload = {
        page: state.currentPage,
        page_size: state.articlesPerPage,
        feed_source_ids: state.activeFeedFilterIds.length > 0 ? state.activeFeedFilterIds : null,
        tag_ids: state.activeTagFilterIds.length > 0 ? state.activeTagFilterIds.map(t => t.id) : null,
        keyword: keyword || null,
        summary_prompt: (state.currentSummaryPrompt !== state.defaultSummaryPrompt) ? state.currentSummaryPrompt : null,
        tag_generation_prompt: (state.currentTagGenerationPrompt !== state.defaultTagGenerationPrompt) ? state.currentTagGenerationPrompt : null,
    };

    try {
        // apiService.fetchNewsSummaries will use state.SUMMARIES_API_ENDPOINT which is set by configManager
        const data = await apiService.fetchNewsSummaries(payload); 
        console.log("MainScript: Received data from fetchNewsSummaries:", data);

        if (page === 1) { 
            state.setTotalArticlesAvailable(data.total_articles_available); 
        }
        state.setTotalPages(data.total_pages);

        uiManager.displayArticleResults(
            data.processed_articles_on_page,
            page === 1, 
            handleArticleTagClick, 
            uiManager.openRegenerateSummaryModal 
        );

        if (page === 1 && data.processed_articles_on_page && data.processed_articles_on_page.length > 0) {
            const newestArticleInBatch = data.processed_articles_on_page.reduce((latest, article) => {
                if (!article.created_at) return latest; 
                const articleDate = new Date(article.created_at);
                return (latest === null || articleDate > latest) ? articleDate : latest;
            }, null);
            if (newestArticleInBatch) {
                if (!state.lastKnownLatestArticleTimestamp || newestArticleInBatch > new Date(state.lastKnownLatestArticleTimestamp)) {
                    state.setLastKnownLatestArticleTimestamp(newestArticleInBatch.toISOString());
                    console.log("MainScript: Updated lastKnownLatestArticleTimestamp to:", state.lastKnownLatestArticleTimestamp);
                }
            }
        }

        if (page === 1 && data.processed_articles_on_page.length === 0 && data.total_articles_available === 0) {
            let noResultsMessage = `<p>No articles found for the current filter (${activeFilterDisplay}).</p>`;
            if (state.dbFeedSources.length === 0 && state.activeTagFilterIds.length === 0 && !keyword) {
                noResultsMessage = '<p>No RSS feeds configured. Please add some in the Setup tab or try searching.</p>';
            }
            uiManager.setResultsContainerContent(noResultsMessage);
        }
        
        if (isPollRefresh && page === 1 && data.processed_articles_on_page.length > 0) {
            console.log("MainScript: New articles loaded via polling.");
        }

    } catch (error) {
        console.error('MainScript: Error fetching or displaying summaries:', error);
        const errorMessage = `<p class="error-message">Error fetching summaries: ${error.message}.</p>`;
        if (page === 1 && !isPollRefresh) { 
            uiManager.setResultsContainerContent(errorMessage);
        } else if (page > 1) {
            const resultsContainer = document.getElementById('results-container');
            if (resultsContainer) {
                const errorP = document.createElement('p');
                errorP.classList.add('error-message');
                errorP.textContent = `Error fetching more articles: ${error.message}`;
                resultsContainer.appendChild(errorP);
            }
        }
        state.setTotalPages(state.currentPage); 
    } finally {
        state.setIsLoadingMoreArticles(false);
        if (!isPollRefresh || page > 1) { 
            uiManager.showLoadingIndicator(false);
        }
        uiManager.showInfiniteScrollLoadingIndicator(false);
        console.log("MainScript: fetchAndDisplaySummaries finished.");
    }
}

async function pollForNewArticles() {
    console.log("MainScript: Polling for new articles. Last known timestamp:", state.lastKnownLatestArticleTimestamp);
    try {
        const pollData = await apiService.checkNewArticles(state.lastKnownLatestArticleTimestamp);
        console.log("MainScript: Poll response:", pollData);
        if (pollData.new_articles_available) {
            console.log(`MainScript: New articles available (Count: ${pollData.article_count}). New server latest_article_timestamp: ${pollData.latest_article_timestamp}. Refreshing view.`);
            // When new articles are found via polling, refresh the view starting from page 1,
            // clearing current keyword search to show all new articles.
            // Pass 'true' for isPollRefresh to potentially alter UI feedback (e.g., no full-page loader).
            if (keywordSearchInput) keywordSearchInput.value = ''; // Clear search UI
            state.setCurrentKeywordSearch(null); // Clear keyword state
            await fetchAndDisplaySummaries(false, 1, null, true); 
        } else {
            console.log("MainScript: No new articles detected by polling. Current server latest_article_timestamp:", pollData.latest_article_timestamp);
        }
        // Always update our knowledge of the server's latest timestamp
        if (pollData.latest_article_timestamp) {
             if (!state.lastKnownLatestArticleTimestamp || new Date(pollData.latest_article_timestamp) > new Date(state.lastKnownLatestArticleTimestamp)) {
                state.setLastKnownLatestArticleTimestamp(pollData.latest_article_timestamp);
                console.log("MainScript: Polling updated lastKnownLatestArticleTimestamp to server's latest:", state.lastKnownLatestArticleTimestamp);
            }
        }
    } catch (error) {
        console.error("MainScript: Error during polling:", error);
    }
}

async function initializeAppSettings() {
    console.log("MainScript: Initializing application settings...");
    uiManager.showLoadingIndicator(true, "Initializing application...");
    try {
        const initialBackendConfig = await apiService.fetchInitialConfigData();
        console.log("MainScript: Initial backend config fetched:", initialBackendConfig);
        
        // configManager.loadConfigurations will use state.setApiEndpoints internally
        configManager.loadConfigurations(initialBackendConfig); 
        
        // Safeguard: Ensure SUMMARIES_API_ENDPOINT is the new one after config loading.
        // This is important if localStorage holds an old value or if backend default wasn't updated.
        if (state.SUMMARIES_API_ENDPOINT === '/api/get-news-summaries') {
            console.warn(`MainScript: SUMMARIES_API_ENDPOINT was found to be the old default '/api/get-news-summaries'. 
                          Updating to '/api/articles/summaries'. 
                          Please ensure your localStorage ('newsSummariesApiEndpoint') 
                          and backend's initial-config default for summaries API are updated if this message repeats.`);
            
            state.setApiEndpoints('/api/articles/summaries', state.CHAT_API_ENDPOINT_BASE); // Use the setter
            
            // If loaded from localStorage, update it too so it's correct next time
            if(localStorage.getItem('newsSummariesApiEndpoint') === '/api/get-news-summaries'){
                localStorage.setItem('newsSummariesApiEndpoint', '/api/articles/summaries');
            }
            // Re-update UI in setup tab if it was based on the old value from localStorage
            configManager.updateSetupUI(); 
        }


        state.setDbFeedSources(initialBackendConfig.all_db_feed_sources || []);
        await feedHandler.loadAndRenderDbFeeds(); 
        uiManager.updateActiveTagFiltersUI(handleRemoveTagFilter); 
        uiManager.showSection('main-feed-section'); 

        if (state.dbFeedSources.length > 0 || state.activeTagFilterIds.length > 0 || state.currentKeywordSearch) {
            await fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch);
        } else {
            uiManager.setResultsContainerContent('<p>No RSS feeds configured. Please add some in the Setup tab, or try searching.</p>');
        }

        if (pollingIntervalId) clearInterval(pollingIntervalId); 
        await pollForNewArticles(); // Initial poll immediately after setup
        pollingIntervalId = setInterval(pollForNewArticles, POLLING_INTERVAL_MS);
        console.log(`MainScript: Started polling for new articles every ${POLLING_INTERVAL_MS / 1000} seconds.`);

    } catch (error) { 
        console.error("MainScript: Error during application initialization:", error);
        uiManager.setResultsContainerContent(`<p class="error-message">Failed to initialize application: ${error.message}</p>`);
    }
    finally { uiManager.showLoadingIndicator(false); }
    console.log("MainScript: Application settings initialization finished.");
}

function handleArticleTagClick(tagId, tagName) {
    console.log(`MainScript: Tag clicked - ID: ${tagId}, Name: ${tagName}`);
    const tagIndex = state.activeTagFilterIds.findIndex(t => t.id === tagId);
    if (tagIndex > -1) { state.removeActiveTagFilter(tagId); } 
    else { state.addActiveTagFilter({ id: tagId, name: tagName }); }
    state.setActiveFeedFilterIds([]);
    state.setCurrentKeywordSearch(null);
    const keywordInput = document.getElementById('keyword-search-input'); // Get ref here
    if(keywordInput) keywordInput.value = ''; 
    uiManager.updateFeedFilterButtonStyles(); 
    uiManager.updateActiveTagFiltersUI(handleRemoveTagFilter); 
    state.setCurrentPage(1);
    fetchAndDisplaySummaries(false, 1, null); 
}

function handleRemoveTagFilter(tagIdToRemove) {
    console.log(`MainScript: Removing tag filter for ID: ${tagIdToRemove}`);
    state.removeActiveTagFilter(tagIdToRemove);
    uiManager.updateActiveTagFiltersUI(handleRemoveTagFilter); 
    document.querySelectorAll(`.article-tag[data-tag-id='${tagIdToRemove}']`).forEach(el => el.classList.remove('active-filter-tag'));
    state.setCurrentPage(1);
    fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch);
}

function handleFeedFilterClick(feedId) {
    console.log(`MainScript: Feed filter clicked for ID: ${feedId}`);
    if (state.activeFeedFilterIds.includes(feedId)) { state.setActiveFeedFilterIds([]); } 
    else { state.setActiveFeedFilterIds([feedId]); }
    state.setActiveTagFilterIds([]);
    state.setCurrentKeywordSearch(null);
    const keywordInput = document.getElementById('keyword-search-input'); // Get ref here
    if(keywordInput) keywordInput.value = '';
    uiManager.updateFeedFilterButtonStyles();
    uiManager.updateActiveTagFiltersUI(handleRemoveTagFilter);
    state.setCurrentPage(1);
    fetchAndDisplaySummaries(false, 1, null); 
}

function handleAllFeedsClick() {
    console.log("MainScript: 'All Feeds' button clicked.");
    if (state.activeFeedFilterIds.length === 0 && state.activeTagFilterIds.length === 0 && !state.currentKeywordSearch) return; 
    state.setActiveFeedFilterIds([]);
    uiManager.updateFeedFilterButtonStyles();
    state.setCurrentPage(1);
    fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch); 
}

async function handleRegenerateSummaryFormSubmit(event) {
    event.preventDefault();
    const articleIdEl = document.getElementById('modal-article-id-input');
    const customPromptEl = document.getElementById('modal-summary-prompt-input');
    if (!articleIdEl || !customPromptEl) { alert("Error: Could not find modal elements."); return; }
    const articleId = articleIdEl.value;
    let customPrompt = customPromptEl.value.trim();
    if (!articleId) { alert("Error: Article ID not found for regeneration."); return; }
    if (customPrompt && !customPrompt.includes("{text}")) { alert("The custom prompt must include the placeholder {text}."); return; }
    if (!customPrompt) customPrompt = null; 
    const summaryElement = document.getElementById(`summary-text-${articleId}`);
    const articleCardElement = document.getElementById(`article-db-${articleId}`);
    const regenButtonOnCard = articleCardElement ? articleCardElement.querySelector('.regenerate-summary-btn') : null;
    if (summaryElement) summaryElement.innerHTML = (typeof marked !== 'undefined' ? marked.parse("Regenerating summary...") : "Regenerating summary...");
    if (regenButtonOnCard) regenButtonOnCard.disabled = true;
    uiManager.closeRegenerateSummaryModal();
    try {
        const updatedArticle = await apiService.regenerateSummary(articleId, { custom_prompt: customPrompt });
        if (summaryElement) {
            summaryElement.innerHTML = typeof marked !== 'undefined' ? marked.parse(updatedArticle.summary || "Summary regenerated, but no content returned.") : (updatedArticle.summary || "Summary regenerated, but no content returned.");
            if (updatedArticle.error_message) {
                 summaryElement.innerHTML += `<p class="error-message">${updatedArticle.error_message}</p>`;
            }
        }
    } catch (error) {
        console.error("MainScript: Error regenerating summary:", error);
        if (summaryElement) summaryElement.innerHTML = `<p class="error-message">Error: ${error.message}</p>`;
        alert(`Failed to regenerate summary: ${error.message}`);
    } finally {
        if (regenButtonOnCard) regenButtonOnCard.disabled = false;
    }
}

function handleRegenerateModalUseDefaultPrompt() {
    const modalSummaryPromptInput = document.getElementById('modal-summary-prompt-input');
    if (modalSummaryPromptInput) {
        modalSummaryPromptInput.value = state.defaultSummaryPrompt;
    }
}

function setupGlobalEventListeners() {
    console.log("MainScript: Setting up global event listeners...");
    // DOM elements like keywordSearchInput are now initialized at the top of this file or within this function.
    keywordSearchInput = document.getElementById('keyword-search-input'); 
    keywordSearchBtn = document.getElementById('keyword-search-btn');

    if (keywordSearchBtn && keywordSearchInput) {
        keywordSearchBtn.addEventListener('click', () => {
            const searchTerm = keywordSearchInput.value.trim();
            state.setCurrentKeywordSearch(searchTerm || null);
            state.setActiveFeedFilterIds([]); state.setActiveTagFilterIds([]);
            uiManager.updateFeedFilterButtonStyles(); uiManager.updateActiveTagFiltersUI(handleRemoveTagFilter);
            state.setCurrentPage(1); fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch);
        });
        keywordSearchInput.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') { event.preventDefault(); keywordSearchBtn.click(); }
        });
    } else { console.warn("MainScript: Keyword search elements not found."); }

    refreshNewsBtn = document.getElementById('refresh-news-btn');
    if (refreshNewsBtn) {
        refreshNewsBtn.addEventListener('click', async () => {
            if (!confirm("This will ask the backend to check all RSS feeds for new articles. This might take a moment. Continue?")) return;
            uiManager.showLoadingIndicator(true, 'Requesting backend to refresh RSS feeds...');
            try {
                const result = await apiService.triggerRssRefresh();
                alert(result.message || "RSS refresh initiated. New articles will appear after processing.");
                setTimeout(() => {
                    state.setCurrentPage(1); 
                    fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch); 
                }, 10000); 
            } catch (error) { console.error("MainScript: Error triggering RSS refresh:", error); alert(`Error triggering refresh: ${error.message}`); } 
            finally { uiManager.showLoadingIndicator(false); }
        });
    } else { console.warn("MainScript: Refresh news button not found."); }
    
    deleteOldDataBtn = document.getElementById('delete-old-data-btn');
    daysOldInput = document.getElementById('days-old-input');
    deleteStatusMessage = document.getElementById('delete-status-message');
    if (deleteOldDataBtn && daysOldInput && deleteStatusMessage) {
        deleteOldDataBtn.addEventListener('click', async () => {
            const days = parseInt(daysOldInput.value);
            if (isNaN(days) || days <= 0) { alert("Please enter a valid positive number of days."); return; }
            if (!confirm(`Are you sure you want to delete all articles older than ${days} days? This cannot be undone.`)) return;
            deleteStatusMessage.textContent = "Deleting old data..."; deleteStatusMessage.style.color = 'inherit';
            try {
                const result = await apiService.deleteOldData(days);
                alert(result.message || "Old data cleanup process completed.");
                deleteStatusMessage.textContent = result.message || "Cleanup complete."; deleteStatusMessage.style.color = 'green';
                state.setCurrentPage(1); fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch);
            } catch (error) {
                console.error("MainScript: Error deleting old data:", error); alert(`Error deleting old data: ${error.message}`);
                deleteStatusMessage.textContent = `Error: ${error.message}`; deleteStatusMessage.style.color = 'red';
            }
        });
    } else { console.warn("MainScript: Delete old data elements not found."); }

    regeneratePromptForm = document.getElementById('regenerate-prompt-form');
    if (regeneratePromptForm) {
        regeneratePromptForm.addEventListener('submit', handleRegenerateSummaryFormSubmit);
    } else { console.warn("MainScript: Regenerate summary form not found."); }

    window.addEventListener('scroll', () => {
        if ((window.innerHeight + window.scrollY) >= (document.body.offsetHeight - 300) && !state.isLoadingMoreArticles && state.currentPage < state.totalPages) {
            console.log("MainScript: Reached bottom of page, loading more articles...");
            state.setCurrentPage(state.currentPage + 1);
            fetchAndDisplaySummaries(false, state.currentPage, state.currentKeywordSearch);
        }
    });
    console.log("MainScript: Global event listeners set up.");
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log("MainScript: DOMContentLoaded event fired. Script execution starting...");

    // Initialize DOM references for all modules first
    uiManager.initializeUIDOMReferences();
    configManager.initializeDOMReferences();
    chatHandler.initializeChatDOMReferences();
    feedHandler.initializeFeedHandlerDOMReferences(() => {
        // This callback allows feedHandler to trigger UI updates for feed filter buttons
        uiManager.renderFeedFilterButtons(handleFeedFilterClick, handleAllFeedsClick);
    });

    // Then setup event listeners for modules that depend on these DOM elements
    uiManager.setupUIManagerEventListeners(handleRegenerateModalUseDefaultPrompt);
    configManager.setupFormEventListeners({
        onArticlesPerPageChange: () => { 
            state.setCurrentPage(1);
            fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch);
        }
    });
    chatHandler.setupChatModalEventListeners();
    feedHandler.setupFeedHandlerEventListeners();
    
    // Setup event listeners handled directly by this main script
    setupGlobalEventListeners(); 
    
    // Initialize application settings and load initial data
    await initializeAppSettings(); 
    
    console.log("MainScript: Full application initialization complete.");
});
