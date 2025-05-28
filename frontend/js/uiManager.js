// frontend/js/uiManager.js
import * as state from './state.js';
import * as apiService from './apiService.js'; 
import * as chatHandler from './chatHandler.js';

/**
 * This module is responsible for all direct UI manipulations,
 * such as rendering articles, updating filter displays, managing loading indicators,
 * and controlling section/modal visibility.
 */

// --- DOM Element References ---
let resultsContainer, loadingIndicator, loadingText, infiniteScrollLoadingIndicator,
    feedFilterControls, activeTagFiltersDisplay,
    mainFeedSection, setupSection, navMainBtn, navSetupBtn,
    regenerateSummaryModal, closeRegenerateModalBtn, modalArticleIdInput, modalSummaryPromptInput, modalUseDefaultPromptBtn,
    fullArticleModal, closeFullArticleModalBtn, fullArticleModalTitle, fullArticleModalBody, fullArticleModalOriginalLink;


/**
 * Initializes DOM references for UI elements.
 */
export function initializeUIDOMReferences() {
    resultsContainer = document.getElementById('results-container');
    loadingIndicator = document.getElementById('loading-indicator');
    loadingText = document.getElementById('loading-text');
    infiniteScrollLoadingIndicator = document.getElementById('infinite-scroll-loading-indicator');
    feedFilterControls = document.getElementById('feed-filter-controls');
    activeTagFiltersDisplay = document.getElementById('active-tag-filters-display');
    mainFeedSection = document.getElementById('main-feed-section');
    setupSection = document.getElementById('setup-section');
    navMainBtn = document.getElementById('nav-main-btn');
    navSetupBtn = document.getElementById('nav-setup-btn');

    regenerateSummaryModal = document.getElementById('regenerate-summary-modal');
    closeRegenerateModalBtn = document.getElementById('close-regenerate-modal-btn');
    modalArticleIdInput = document.getElementById('modal-article-id-input'); 
    modalSummaryPromptInput = document.getElementById('modal-summary-prompt-input'); 
    modalUseDefaultPromptBtn = document.getElementById('modal-use-default-prompt-btn');

    fullArticleModal = document.getElementById('full-article-modal');
    closeFullArticleModalBtn = document.getElementById('close-full-article-modal-btn');
    fullArticleModalTitle = document.getElementById('full-article-modal-title');
    fullArticleModalBody = document.getElementById('full-article-modal-body');
    fullArticleModalOriginalLink = document.getElementById('full-article-modal-original-link');

    console.log("UIManager: DOM references initialized.");
    if (!resultsContainer) console.error("UIManager: results-container not found!");
    if (!fullArticleModal) console.warn("UIManager: full-article-modal not found!");
}

/**
 * Shows or hides the main loading indicator.
 */
export function showLoadingIndicator(show, message = "Loading...") {
    if (loadingIndicator && loadingText) {
        loadingText.textContent = message;
        loadingIndicator.style.display = show ? 'flex' : 'none';
    } else {
        console.warn("UIManager: Main loading indicator elements not found.");
    }
}

/**
 * Shows or hides the infinite scroll loading indicator.
 */
export function showInfiniteScrollLoadingIndicator(show) {
    if (infiniteScrollLoadingIndicator) {
        infiniteScrollLoadingIndicator.style.display = show ? 'flex' : 'none';
    } else {
        console.warn("UIManager: Infinite scroll loading indicator not found.");
    }
}

/**
 * Opens the Full Article Content modal and fetches/displays content.
 */
export async function openAndLoadFullArticleModal(articleId, articleTitle, originalUrl) {
    if (!fullArticleModal || !fullArticleModalTitle || !fullArticleModalBody || !fullArticleModalOriginalLink) {
        console.error("UIManager: Full article modal elements not found. Cannot open.");
        return;
    }

    fullArticleModalTitle.textContent = articleTitle || "Full Article";
    fullArticleModalBody.innerHTML = '<p class="loading-text-modal">Loading full article content...</p>'; 
    fullArticleModalOriginalLink.href = originalUrl || "#";
    fullArticleModalOriginalLink.textContent = "View Original on Publisher's Site";

    fullArticleModal.style.display = "block";
    console.log(`UIManager: Opening full article modal for article ID: ${articleId}`);

    try {
        const contentData = await apiService.fetchSanitizedArticleContent(articleId);
        if (contentData.error_message) {
            fullArticleModalBody.innerHTML = `<p class="error-message">${contentData.error_message}</p>`;
            // Corrected logger usage:
            console.warn(`UIManager: Error fetching sanitized content for article ${articleId}: ${contentData.error_message}`);
        } else if (contentData.sanitized_html_content) {
            fullArticleModalBody.innerHTML = contentData.sanitized_html_content;
        } else {
            fullArticleModalBody.innerHTML = "<p>Full article content could not be loaded or is empty.</p>";
        }
        if(contentData.title) fullArticleModalTitle.textContent = contentData.title;
        if(contentData.original_url) fullArticleModalOriginalLink.href = contentData.original_url;

    } catch (error) {
        console.error(`UIManager: Failed to fetch or display sanitized content for article ${articleId}:`, error);
        fullArticleModalBody.innerHTML = `<p class="error-message">Error loading content: ${error.message}</p>`;
    }
}

/**
 * Closes the Full Article Content modal.
 */
export function closeFullArticleModal() {
    if (fullArticleModal) {
        fullArticleModal.style.display = "none";
        if(fullArticleModalBody) fullArticleModalBody.innerHTML = ''; 
    }
    console.log("UIManager: Full article modal closed.");
}


/**
 * Displays article results in the results container.
 */
export function displayArticleResults(articles, clearPrevious, onTagClickCallback, onRegenerateClickCallback) {
    if (!resultsContainer) {
        console.error("UIManager: resultsContainer is null! Cannot display articles.");
        return;
    }
    if (clearPrevious) {
        resultsContainer.innerHTML = '';
    }

    if (!articles || articles.length === 0) {
        console.log("UIManager: No new articles to display.");
        return;
    }

    articles.forEach((article) => {
        const articleCard = document.createElement('div');
        articleCard.classList.add('article-card');
        articleCard.setAttribute('id', `article-db-${article.id}`);

        // --- ICON PLACEMENT FIX ---
        // Regenerate Summary Button and Direct Link Icon are appended DIRECTLY to articleCard
        // Their CSS in article_card.css uses position: absolute relative to articleCard.
        // NO .article-card-actions wrapper div is used here.

        const regenButton = document.createElement('button');
        regenButton.classList.add('regenerate-summary-btn');
        regenButton.title = "Regenerate Summary";
        regenButton.onclick = () => {
            if (onRegenerateClickCallback && typeof onRegenerateClickCallback === 'function') {
                onRegenerateClickCallback(article.id);
            }
        };
        articleCard.appendChild(regenButton); // Append directly

        const directLinkIcon = document.createElement('a');
        directLinkIcon.href = article.url;
        directLinkIcon.target = "_blank";
        directLinkIcon.rel = "noopener noreferrer";
        directLinkIcon.classList.add('direct-link-icon');
        directLinkIcon.title = "View Original Article";
        directLinkIcon.innerHTML = "&#128279;"; // Link symbol emoji 
        articleCard.appendChild(directLinkIcon); // Append directly

        // --- End of ICON PLACEMENT FIX ---

        const titleEl = document.createElement('h3');
        titleEl.textContent = article.title || 'No Title Provided';
        articleCard.appendChild(titleEl);

        const metaInfo = document.createElement('div');
        metaInfo.classList.add('article-meta-info');
        if (article.publisher) {
            const p = document.createElement('span');
            p.classList.add('article-publisher');
            p.textContent = `Source: ${article.publisher}`;
            metaInfo.appendChild(p);
        }
        if (article.published_date) {
            const d = document.createElement('span');
            d.classList.add('article-published-date');
            try {
                d.textContent = `Published: ${new Date(article.published_date).toLocaleString(undefined, { year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: 'numeric' })}`;
            } catch (e) {
                d.textContent = `Published: ${article.published_date}`;
            }
            metaInfo.appendChild(d);
        }
        if (metaInfo.hasChildNodes()) articleCard.appendChild(metaInfo);

        const readFullArticleBtn = document.createElement('button'); 
        readFullArticleBtn.textContent = 'Read Full Article (In-App)';
        readFullArticleBtn.classList.add('read-full-article-btn'); 
        readFullArticleBtn.onclick = () => openAndLoadFullArticleModal(article.id, article.title, article.url);
        articleCard.appendChild(readFullArticleBtn);

        const summaryP = document.createElement('div');
        summaryP.classList.add('summary');
        summaryP.setAttribute('id', `summary-text-${article.id}`);
        summaryP.innerHTML = typeof marked !== 'undefined' ? marked.parse(article.summary || "No summary available.") : (article.summary || "No summary available.");
        articleCard.appendChild(summaryP);

        if (article.tags && article.tags.length > 0) {
            const tagsContainer = document.createElement('div');
            tagsContainer.classList.add('article-tags-container');
            article.tags.forEach(tag => {
                const tagEl = document.createElement('span');
                tagEl.classList.add('article-tag');
                tagEl.textContent = tag.name;
                tagEl.setAttribute('data-tag-id', tag.id.toString());
                tagEl.setAttribute('data-tag-name', tag.name);
                if (state.activeTagFilterIds.some(activeTag => activeTag.id === tag.id)) {
                    tagEl.classList.add('active-filter-tag');
                }
                tagEl.onclick = () => {
                    if (onTagClickCallback && typeof onTagClickCallback === 'function') {
                        onTagClickCallback(tag.id, tag.name);
                    }
                };
                tagsContainer.appendChild(tagEl);
            });
            articleCard.appendChild(tagsContainer);
        }

        if (article.error_message && !article.summary) {
            const err = document.createElement('p');
            err.classList.add('error-message');
            err.innerHTML = typeof marked !== 'undefined' ? marked.parse(article.error_message) : article.error_message;
            articleCard.appendChild(err);
        }

        const openChatBtn = document.createElement('button');
        openChatBtn.classList.add('open-chat-modal-btn');
        openChatBtn.textContent = 'Chat about this article';
        openChatBtn.onclick = () => chatHandler.openArticleChatModal(article);
        articleCard.appendChild(openChatBtn);

        resultsContainer.appendChild(articleCard);
    });
    console.log("UIManager: Finished appending article cards.");
}

/**
 * Renders the feed filter buttons.
 */
export function renderFeedFilterButtons(onFeedFilterClick, onAllFeedsClick) {
    if (!feedFilterControls) {
        console.warn("UIManager: feedFilterControls element not found.");
        return;
    }
    feedFilterControls.innerHTML = '';
    const allFeedsButton = document.createElement('button');
    allFeedsButton.textContent = 'All Feeds';
    allFeedsButton.onclick = onAllFeedsClick;
    feedFilterControls.appendChild(allFeedsButton);
    state.dbFeedSources.forEach(feed => {
        const feedButton = document.createElement('button');
        let displayName = feed.name || (feed.url ? feed.url.split('/')[2]?.replace(/^www\./, '') : 'Unknown Feed');
        if (displayName.length > 30) displayName = displayName.substring(0, 27) + "..."; 
        feedButton.textContent = displayName;
        feedButton.title = `${feed.name || 'Unnamed Feed'} (${feed.url})`; 
        feedButton.setAttribute('data-feedid', feed.id.toString());
        feedButton.onclick = () => onFeedFilterClick(feed.id);
        feedFilterControls.appendChild(feedButton);
    });
    updateFeedFilterButtonStyles();
}

/**
 * Updates the visual style of feed filter buttons.
 */
export function updateFeedFilterButtonStyles() {
    if (!feedFilterControls) return;
    const buttons = feedFilterControls.querySelectorAll('button');
    buttons.forEach(button => {
        button.classList.remove('active'); 
        const feedIdAttr = button.getAttribute('data-feedid');
        if (state.activeFeedFilterIds.length === 0 && button.textContent === 'All Feeds') {
            button.classList.add('active');
        } else if (feedIdAttr && state.activeFeedFilterIds.includes(parseInt(feedIdAttr))) {
            button.classList.add('active');
        }
    });
}

/**
 * Updates the UI to display active tag filters.
 */
export function updateActiveTagFiltersUI(onRemoveTagFilterCallback) {
    if (!activeTagFiltersDisplay) {
        console.warn("UIManager: activeTagFiltersDisplay element not found.");
        return;
    }
    activeTagFiltersDisplay.innerHTML = '';
    if (state.activeTagFilterIds.length === 0) {
        activeTagFiltersDisplay.style.display = 'none';
        return;
    }
    activeTagFiltersDisplay.style.display = 'block';
    const heading = document.createElement('span');
    heading.textContent = 'Filtered by tags: ';
    heading.style.fontWeight = 'bold';
    activeTagFiltersDisplay.appendChild(heading);
    state.activeTagFilterIds.forEach(tagObj => {
        const tagSpan = document.createElement('span');
        tagSpan.classList.add('active-tag-filter');
        tagSpan.textContent = tagObj.name;
        const removeBtn = document.createElement('span');
        removeBtn.classList.add('remove-tag-filter-btn');
        removeBtn.textContent = '×';
        removeBtn.title = `Remove filter: ${tagObj.name}`;
        removeBtn.onclick = () => {
            if (onRemoveTagFilterCallback && typeof onRemoveTagFilterCallback === 'function') {
                onRemoveTagFilterCallback(tagObj.id);
            }
        };
        tagSpan.appendChild(removeBtn);
        activeTagFiltersDisplay.appendChild(tagSpan);
    });
}

/**
 * Shows a specific section.
 */
export function showSection(sectionId) {
    if (!mainFeedSection || !setupSection || !navMainBtn || !navSetupBtn) {
        console.error("UIManager: One or more navigation/section elements not found.");
        return;
    }
    mainFeedSection.classList.remove('active');
    setupSection.classList.remove('active');
    navMainBtn.classList.remove('active');
    navSetupBtn.classList.remove('active');
    const sectionToShow = document.getElementById(sectionId);
    if (sectionToShow) {
        sectionToShow.classList.add('active');
    } else {
        console.error(`UIManager: Section with ID '${sectionId}' not found.`);
    }
    if (sectionId === 'main-feed-section' && navMainBtn) {
        navMainBtn.classList.add('active');
    } else if (sectionId === 'setup-section' && navSetupBtn) {
        navSetupBtn.classList.add('active');
    }
    console.log(`UIManager: Switched to section: ${sectionId}`);
}

/**
 * Opens the regenerate summary modal.
 */
export function openRegenerateSummaryModal(articleId) {
    if (!regenerateSummaryModal || !modalArticleIdInput || !modalSummaryPromptInput) {
        console.error("UIManager: Regenerate summary modal elements not found. Cannot open.");
        return;
    }
    modalArticleIdInput.value = articleId.toString();
    modalSummaryPromptInput.value = state.currentSummaryPrompt || state.defaultSummaryPrompt;
    regenerateSummaryModal.style.display = "block";
    console.log(`UIManager: Opened regenerate summary modal for article ID: ${articleId}`);
}

/**
 * Closes the regenerate summary modal.
 */
export function closeRegenerateSummaryModal() {
    if (regenerateSummaryModal) {
        regenerateSummaryModal.style.display = "none";
    }
    console.log("UIManager: Regenerate summary modal closed.");
}

/**
 * Sets up basic event listeners for UI elements managed by UIManager.
 */
export function setupUIManagerEventListeners(onRegenerateModalUseDefaultPrompt) {
    if (closeRegenerateModalBtn) {
        closeRegenerateModalBtn.onclick = closeRegenerateSummaryModal;
    }
    if (modalUseDefaultPromptBtn && typeof onRegenerateModalUseDefaultPrompt === 'function') {
        modalUseDefaultPromptBtn.onclick = onRegenerateModalUseDefaultPrompt;
    }
    window.addEventListener('click', function(event) {
        if (regenerateSummaryModal && event.target === regenerateSummaryModal) {
            closeRegenerateSummaryModal();
        }
        if (fullArticleModal && event.target === fullArticleModal) {
            closeFullArticleModal();
        }
    });
    if (closeFullArticleModalBtn) {
        closeFullArticleModalBtn.onclick = closeFullArticleModal;
    }
    if (navMainBtn) navMainBtn.addEventListener('click', () => showSection('main-feed-section'));
    if (navSetupBtn) navSetupBtn.addEventListener('click', () => showSection('setup-section'));
    console.log("UIManager: Basic event listeners set up.");
}

/**
 * Sets the content of the results container.
 */
export function setResultsContainerContent(htmlContent) {
    if (resultsContainer) {
        resultsContainer.innerHTML = htmlContent;
    } else {
        console.error("UIManager: resultsContainer not found, cannot set content.");
    }
}

console.log("frontend/js/uiManager.js: Module loaded.");
