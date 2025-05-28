// frontend/js/uiManager.js
import * as state from './state.js';
// Import chatHandler if its functions are directly called for opening modals from article cards
import * as chatHandler from './chatHandler.js';
// We'll need a way to open the regenerate summary modal. This might be a local function
// or imported if we create a dedicated modal manager or if configManager handles it.
// For now, let's assume a local function or one to be defined in the main script.

/**
 * This module is responsible for all direct UI manipulations,
 * such as rendering articles, updating filter displays, managing loading indicators,
 * and controlling section/modal visibility.
 */

// --- DOM Element References ---
let resultsContainer, loadingIndicator, loadingText, infiniteScrollLoadingIndicator,
    feedFilterControls, activeTagFiltersDisplay,
    mainFeedSection, setupSection, navMainBtn, navSetupBtn,
    regenerateSummaryModal, closeRegenerateModalBtn, modalArticleIdInput, modalSummaryPromptInput, modalUseDefaultPromptBtn;
    // Note: Regenerate summary modal elements are listed here. Their event handling
    // might be in configManager.js or the main script, but uiManager can control visibility.

/**
 * Initializes DOM references for UI elements.
 * Should be called once the DOM is ready.
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

    // Regenerate Summary Modal Elements
    regenerateSummaryModal = document.getElementById('regenerate-summary-modal');
    closeRegenerateModalBtn = document.getElementById('close-regenerate-modal-btn');
    modalArticleIdInput = document.getElementById('modal-article-id-input'); // Used to set article ID
    modalSummaryPromptInput = document.getElementById('modal-summary-prompt-input'); // Used to set prompt
    modalUseDefaultPromptBtn = document.getElementById('modal-use-default-prompt-btn');


    console.log("UIManager: DOM references initialized.");
    if (!resultsContainer) console.error("UIManager: results-container not found!");
    if (!loadingIndicator) console.error("UIManager: loading-indicator not found!");
}

/**
 * Shows or hides the main loading indicator.
 * @param {boolean} show - True to show, false to hide.
 * @param {string} [message] - Optional message to display.
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
 * @param {boolean} show - True to show, false to hide.
 */
export function showInfiniteScrollLoadingIndicator(show) {
    if (infiniteScrollLoadingIndicator) {
        infiniteScrollLoadingIndicator.style.display = show ? 'flex' : 'none';
    } else {
        console.warn("UIManager: Infinite scroll loading indicator not found.");
    }
}

/**
 * Displays article results in the results container.
 * @param {Array<object>} articles - Array of article objects to display.
 * @param {boolean} clearPrevious - True to clear existing articles, false to append.
 * @param {function} onTagClickCallback - Callback function when a tag is clicked.
 * @param {function} onRegenerateClickCallback - Callback for regenerate summary button.
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
        if (clearPrevious && state.currentPage === 1 && !state.currentKeywordSearch && state.activeTagFilterIds.length === 0 && state.activeFeedFilterIds.length === 0) {
            // Only show "no articles" if it's an initial load with no filters and no results.
            // resultsContainer.innerHTML = '<p>No articles found for the current filter.</p>';
        }
        console.log("UIManager: No new articles to display.");
        return;
    }

    articles.forEach((article) => {
        const articleCard = document.createElement('div');
        articleCard.classList.add('article-card');
        articleCard.setAttribute('id', `article-db-${article.id}`);

        const regenButton = document.createElement('button');
        regenButton.classList.add('regenerate-summary-btn');
        regenButton.title = "Regenerate Summary";
        regenButton.onclick = () => {
            if (onRegenerateClickCallback && typeof onRegenerateClickCallback === 'function') {
                onRegenerateClickCallback(article.id);
            } else {
                console.warn("UIManager: onRegenerateClickCallback not provided for article card.");
            }
        };
        articleCard.appendChild(regenButton);

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

        if (article.url) {
            const l = document.createElement('a');
            l.href = article.url;
            l.textContent = 'Read Full Article';
            l.classList.add('source-link');
            l.target = '_blank';
            l.rel = 'noopener noreferrer';
            articleCard.appendChild(l);
        }

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
        openChatBtn.onclick = () => chatHandler.openArticleChatModal(article); // Directly call chatHandler
        articleCard.appendChild(openChatBtn);

        resultsContainer.appendChild(articleCard);
    });
    console.log("UIManager: Finished appending article cards.");
}

/**
 * Renders the feed filter buttons based on dbFeedSources from state.
 * @param {function} onFeedFilterClick - Callback when a feed filter button is clicked.
 * @param {function} onAllFeedsClick - Callback when 'All Feeds' button is clicked.
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
        // Attempt to get a display name
        let displayName = feed.name || (feed.url ? feed.url.split('/')[2]?.replace(/^www\./, '') : 'Unknown Feed');
        if (displayName.length > 30) displayName = displayName.substring(0, 27) + "..."; // Truncate long names
        feedButton.textContent = displayName;
        feedButton.title = `${feed.name || 'Unnamed Feed'} (${feed.url})`; // Full details on hover
        feedButton.setAttribute('data-feedid', feed.id.toString());
        feedButton.onclick = () => onFeedFilterClick(feed.id);
        feedFilterControls.appendChild(feedButton);
    });
    updateFeedFilterButtonStyles(); // Apply active styles
}

/**
 * Updates the visual style of feed filter buttons to show active filters.
 */
export function updateFeedFilterButtonStyles() {
    if (!feedFilterControls) return;
    const buttons = feedFilterControls.querySelectorAll('button');
    buttons.forEach(button => {
        button.classList.remove('active'); // Remove active from all first
        const feedIdAttr = button.getAttribute('data-feedid');
        if (state.activeFeedFilterIds.length === 0 && button.textContent === 'All Feeds') {
            button.classList.add('active');
        } else if (feedIdAttr && state.activeFeedFilterIds.includes(parseInt(feedIdAttr))) {
            button.classList.add('active');
        }
    });
}

/**
 * Updates the UI to display the currently active tag filters.
 * @param {function} onRemoveTagFilterCallback - Callback when a tag filter remove button is clicked.
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
 * Shows a specific section (e.g., main feed or setup) and hides others.
 * @param {string} sectionId - The ID of the section to show.
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
 * Opens the regenerate summary modal and pre-fills it.
 * @param {number} articleId - The ID of the article.
 */
export function openRegenerateSummaryModal(articleId) {
    if (!regenerateSummaryModal || !modalArticleIdInput || !modalSummaryPromptInput) {
        console.error("UIManager: Regenerate summary modal elements not found. Cannot open.");
        return;
    }
    modalArticleIdInput.value = articleId.toString();
    modalSummaryPromptInput.value = state.currentSummaryPrompt || state.defaultSummaryPrompt; // Use current or default
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
 * Sets up basic event listeners for UI elements managed by UIManager, like modal close buttons.
 * More complex event listeners (forms, dynamic content) might be set up by their respective handlers or the main script.
 * @param {function} onRegenerateModalUseDefaultPrompt - Callback for 'Use Default' button in regen modal.
 * @param {function} onRegenerateModalSubmit - Callback for regen modal form submission.
 */
export function setupUIManagerEventListeners(onRegenerateModalUseDefaultPrompt, onRegenerateModalSubmit) {
    if (closeRegenerateModalBtn) {
        closeRegenerateModalBtn.onclick = closeRegenerateSummaryModal;
    }
    if (modalUseDefaultPromptBtn && typeof onRegenerateModalUseDefaultPrompt === 'function') {
        modalUseDefaultPromptBtn.onclick = onRegenerateModalUseDefaultPrompt;
    }
    
    // Regenerate modal form submission is handled by the main script or configManager,
    // but closing on window click can be here.
    window.addEventListener('click', function(event) {
        if (regenerateSummaryModal && event.target === regenerateSummaryModal) {
            closeRegenerateSummaryModal();
        }
    });

    // Navigation buttons
    if (navMainBtn) navMainBtn.addEventListener('click', () => showSection('main-feed-section'));
    if (navSetupBtn) navSetupBtn.addEventListener('click', () => showSection('setup-section'));

    console.log("UIManager: Basic event listeners set up.");
}

/**
 * Sets the content of the results container, typically used for messages like "No feeds configured".
 * @param {string} htmlContent - The HTML content to set.
 */
export function setResultsContainerContent(htmlContent) {
    if (resultsContainer) {
        resultsContainer.innerHTML = htmlContent;
    } else {
        console.error("UIManager: resultsContainer not found, cannot set content.");
    }
}


console.log("frontend/js/uiManager.js: Module loaded.");
