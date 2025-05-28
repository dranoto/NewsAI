// frontend/js/configManager.js
import * as state from './state.js';
// We might need to import a function to refresh the main feed if settings like 'articlesPerPage' change.
// For now, we'll assume such a function (e.g., fetchAndDisplaySummaries) is globally available or imported into the main script.

/**
 * This module handles loading, saving, and applying application configurations.
 * It interacts with localStorage for persistence and updates the UI in the setup tab.
 */

// --- DOM Element References for the Setup Tab ---
// It's good practice to get these once, or ensure they are valid before use.
// These could also be passed in if this module becomes more generic.
let numArticlesSetupInput, currentNumArticlesDisplay,
    apiUrlInput, currentApiUrlDisplay,
    chatApiUrlInput, currentChatApiUrlDisplay,
    summaryPromptInput, currentSummaryPromptDisplay,
    tagGenerationPromptInput, currentTagGenerationPromptDisplay,
    chatPromptInput, currentChatPromptDisplay,
    rssFetchIntervalInput, currentRssFetchIntervalDisplay,
    contentPrefsForm, apiEndpointForm, aiPromptsForm, globalRssSettingsForm, resetPromptsBtn;


/**
 * Initializes the configuration manager by fetching DOM elements.
 * This should be called once the DOM is ready.
 */
export function initializeDOMReferences() {
    numArticlesSetupInput = document.getElementById('num_articles_setup');
    currentNumArticlesDisplay = document.getElementById('current-num-articles-display');
    apiUrlInput = document.getElementById('api-url');
    currentApiUrlDisplay = document.getElementById('current-api-url-display');
    chatApiUrlInput = document.getElementById('chat-api-url');
    currentChatApiUrlDisplay = document.getElementById('current-chat-api-url-display');
    summaryPromptInput = document.getElementById('summary-prompt-input');
    currentSummaryPromptDisplay = document.getElementById('current-summary-prompt-display');
    tagGenerationPromptInput = document.getElementById('tag-generation-prompt-input');
    currentTagGenerationPromptDisplay = document.getElementById('current-tag-generation-prompt-display');
    chatPromptInput = document.getElementById('chat-prompt-input');
    currentChatPromptDisplay = document.getElementById('current-chat-prompt-display');
    rssFetchIntervalInput = document.getElementById('rss-fetch-interval-input');
    currentRssFetchIntervalDisplay = document.getElementById('current-rss-fetch-interval-display');

    contentPrefsForm = document.getElementById('content-prefs-form');
    apiEndpointForm = document.getElementById('api-endpoint-form');
    aiPromptsForm = document.getElementById('ai-prompts-form');
    globalRssSettingsForm = document.getElementById('global-rss-settings-form');
    resetPromptsBtn = document.getElementById('reset-prompts-btn');

    console.log("ConfigManager: DOM references initialized.");
}


/**
 * Loads all configurations from localStorage and applies them to the state.
 * Also updates the UI elements in the setup tab.
 * @param {object} initialBackendConfig - Config data fetched from the backend (e.g., default prompts).
 */
export function loadConfigurations(initialBackendConfig) {
    console.log("ConfigManager: Loading configurations...");

    // Articles per page
    const storedArticlesPerPage = localStorage.getItem('articlesPerPage');
    if (storedArticlesPerPage) {
        state.setArticlesPerPage(parseInt(storedArticlesPerPage));
    } else if (initialBackendConfig && initialBackendConfig.default_articles_per_page) {
        state.setArticlesPerPage(initialBackendConfig.default_articles_per_page);
    }

    // API Endpoints
    const storedSummariesEndpoint = localStorage.getItem('newsSummariesApiEndpoint');
    const storedChatEndpointBase = localStorage.getItem('newsChatApiEndpoint'); // This was the full path in old script
    
    let chatApiBase = initialBackendConfig.default_chat_api_base || '/api'; // Assuming a default base
    if (storedChatEndpointBase) {
        // Derive base from full path if it was stored that way
        chatApiBase = storedChatEndpointBase.endsWith('/chat-with-article') 
            ? storedChatEndpointBase.substring(0, storedChatEndpointBase.lastIndexOf('/')) 
            : storedChatEndpointBase;
        if (!chatApiBase) chatApiBase = '/api'; // Fallback if substring results in empty
    }
    state.setApiEndpoints(
        storedSummariesEndpoint || initialBackendConfig.default_summaries_api_endpoint || '/api/get-news-summaries',
        chatApiBase
    );


    // AI Prompts - Use defaults from backend config first if no localStorage override
    state.setDefaultPrompts(
        initialBackendConfig.default_summary_prompt,
        initialBackendConfig.default_chat_prompt,
        initialBackendConfig.default_tag_generation_prompt
    );
    state.setCurrentPrompts(
        localStorage.getItem('customSummaryPrompt') || state.defaultSummaryPrompt,
        localStorage.getItem('customChatPrompt') || state.defaultChatPrompt,
        localStorage.getItem('customTagGenerationPrompt') || state.defaultTagGenerationPrompt
    );

    // Global RSS Fetch Interval
    // Note: This is a frontend preference. The actual backend scheduler interval is set in backend config.
    // This frontend setting is primarily for when new feeds are added via UI without specifying an interval.
    const storedGlobalRssInterval = localStorage.getItem('globalRssFetchInterval');
    if (storedGlobalRssInterval) {
        state.setGlobalRssFetchInterval(parseInt(storedGlobalRssInterval));
    } else if (initialBackendConfig && initialBackendConfig.default_rss_fetch_interval_minutes) {
        state.setGlobalRssFetchInterval(initialBackendConfig.default_rss_fetch_interval_minutes);
    }
    
    updateSetupUI();
    console.log("ConfigManager: Configurations loaded and UI updated.");
}

/**
 * Updates the input fields and display elements in the Setup Tab with current configuration values.
 */
export function updateSetupUI() {
    if (!numArticlesSetupInput) { // Check if DOM refs are initialized
        console.warn("ConfigManager: updateSetupUI called before DOM references were initialized. Call initializeDOMReferences first.");
        initializeDOMReferences(); // Attempt to initialize if not already
        if(!numArticlesSetupInput) { // If still not available, exit
            console.error("ConfigManager: DOM elements for setup UI not found even after re-init. Cannot update UI.");
            return;
        }
    }

    if (numArticlesSetupInput) numArticlesSetupInput.value = state.articlesPerPage;
    if (currentNumArticlesDisplay) currentNumArticlesDisplay.textContent = state.articlesPerPage;

    if (apiUrlInput) apiUrlInput.value = state.SUMMARIES_API_ENDPOINT;
    if (currentApiUrlDisplay) currentApiUrlDisplay.textContent = state.SUMMARIES_API_ENDPOINT;
    
    // CHAT_API_ENDPOINT_BASE is just the base, the input shows the full example endpoint
    if (chatApiUrlInput) chatApiUrlInput.value = `${state.CHAT_API_ENDPOINT_BASE}/chat-with-article`;
    if (currentChatApiUrlDisplay) currentChatApiUrlDisplay.textContent = `${state.CHAT_API_ENDPOINT_BASE}/chat-with-article`;

    if (summaryPromptInput) summaryPromptInput.value = state.currentSummaryPrompt;
    if (currentSummaryPromptDisplay) currentSummaryPromptDisplay.textContent = state.currentSummaryPrompt;
    if (tagGenerationPromptInput) tagGenerationPromptInput.value = state.currentTagGenerationPrompt;
    if (currentTagGenerationPromptDisplay) currentTagGenerationPromptDisplay.textContent = state.currentTagGenerationPrompt;
    if (chatPromptInput) chatPromptInput.value = state.currentChatPrompt;
    if (currentChatPromptDisplay) currentChatPromptDisplay.textContent = state.currentChatPrompt;

    if (rssFetchIntervalInput) rssFetchIntervalInput.value = state.globalRssFetchInterval;
    if (currentRssFetchIntervalDisplay) currentRssFetchIntervalDisplay.textContent = state.globalRssFetchInterval;
    console.log("ConfigManager: Setup UI elements updated.");
}

/**
 * Saves the "Articles per Page" setting.
 * @param {number} count - The new number of articles per page.
 * @param {function} [callback] - Optional callback to execute after saving, e.g., to refresh the feed.
 */
export function saveArticlesPerPage(count, callback) {
    const newArticlesPerPage = parseInt(count);
    if (newArticlesPerPage >= 1 && newArticlesPerPage <= 50) { // Max 50, adjust as needed
        state.setArticlesPerPage(newArticlesPerPage);
        localStorage.setItem('articlesPerPage', newArticlesPerPage.toString());
        updateSetupUI();
        alert('Content preferences saved! Articles per page set to ' + newArticlesPerPage);
        state.setCurrentPage(1); // Reset to first page
        if (callback && typeof callback === 'function') {
            callback(); // e.g., fetchAndDisplaySummaries(false, 1, state.currentKeywordSearch)
        }
    } else {
        alert('Please enter a number of articles per page between 1 and 50.');
    }
}

/**
 * Saves the API endpoint settings.
 * @param {string} newSummariesApiUrl - The new URL for the summaries API.
 * @param {string} newChatApiUrlFullPath - The new full URL for the chat API (e.g., /api/chat-with-article).
 */
export function saveApiEndpoints(newSummariesApiUrl, newChatApiUrlFullPath) {
    let updated = false;
    if (newSummariesApiUrl && newSummariesApiUrl.trim()) {
        state.SUMMARIES_API_ENDPOINT = newSummariesApiUrl.trim(); // Direct update, or use setter
        localStorage.setItem('newsSummariesApiEndpoint', state.SUMMARIES_API_ENDPOINT);
        updated = true;
    }
    if (newChatApiUrlFullPath && newChatApiUrlFullPath.trim()) {
        localStorage.setItem('newsChatApiEndpoint', newChatApiUrlFullPath.trim()); // Store the full path
        // Derive base for state.CHAT_API_ENDPOINT_BASE
        let chatBase = newChatApiUrlFullPath.trim();
        if (chatBase.endsWith('/chat-with-article')) {
            chatBase = chatBase.substring(0, chatBase.lastIndexOf('/'));
        }
        state.CHAT_API_ENDPOINT_BASE = chatBase || '/api'; // Fallback if substring is empty
        updated = true;
    }
    if (updated) {
        updateSetupUI();
        alert('API Endpoints updated!');
    }
}

/**
 * Saves the custom AI prompt settings.
 * @param {string} newSummaryPrompt
 * @param {string} newChatPrompt
 * @param {string} newTagGenerationPrompt
 */
export function saveAiPrompts(newSummaryPrompt, newChatPrompt, newTagGenerationPrompt) {
    if (newSummaryPrompt && !newSummaryPrompt.includes("{text}")) {
        alert("Summary prompt must contain the placeholder {text}."); return;
    }
    if (newTagGenerationPrompt && !newTagGenerationPrompt.includes("{text}")) {
        alert("Tag Generation prompt must contain the placeholder {text}."); return;
    }
    // Looser validation for chat prompt, as per original script
    if (newChatPrompt && !newChatPrompt.includes("{question}")) {
        alert("Chat prompt should ideally include {question}. It's also recommended to include {article_text}.");
        // Allow saving even if {article_text} is missing
    }

    state.setCurrentPrompts(
        newSummaryPrompt.trim() || state.defaultSummaryPrompt,
        newChatPrompt.trim() || state.defaultChatPrompt,
        newTagGenerationPrompt.trim() || state.defaultTagGenerationPrompt
    );

    localStorage.setItem('customSummaryPrompt', state.currentSummaryPrompt);
    localStorage.setItem('customChatPrompt', state.currentChatPrompt);
    localStorage.setItem('customTagGenerationPrompt', state.currentTagGenerationPrompt);

    updateSetupUI();
    alert('AI Prompts saved!');
}

/**
 * Resets AI prompts to their default values.
 */
export function resetAiPromptsToDefaults() {
    if (confirm("Are you sure you want to reset prompts to their default values?")) {
        state.setCurrentPrompts(state.defaultSummaryPrompt, state.defaultChatPrompt, state.defaultTagGenerationPrompt);

        localStorage.removeItem('customSummaryPrompt');
        localStorage.removeItem('customChatPrompt');
        localStorage.removeItem('customTagGenerationPrompt');
        
        updateSetupUI();
        alert('Prompts have been reset to defaults.');
    }
}

/**
 * Saves the global RSS fetch interval preference.
 * @param {number} interval - The new interval in minutes.
 */
export function saveGlobalRssFetchInterval(interval) {
    const newInterval = parseInt(interval);
    if (!isNaN(newInterval) && newInterval >= 5) { // Min 5 minutes
        state.setGlobalRssFetchInterval(newInterval);
        localStorage.setItem('globalRssFetchInterval', newInterval.toString());
        updateSetupUI();
        alert(`Default RSS fetch interval preference updated to ${newInterval} minutes. This applies when adding new feeds without a specific interval.`);
    } else {
        alert("Please enter a valid interval (minimum 5 minutes).");
    }
}


/**
 * Attaches event listeners to the forms in the Setup Tab.
 * @param {object} callbacks - Object containing callbacks, e.g., { onArticlesPerPageChange: function }
 */
export function setupFormEventListeners(callbacks = {}) {
    if (!contentPrefsForm) {
        console.warn("ConfigManager: Forms not found, cannot attach event listeners. Call initializeDOMReferences first.");
        return;
    }

    if (contentPrefsForm) {
        contentPrefsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (numArticlesSetupInput) {
                saveArticlesPerPage(numArticlesSetupInput.value, callbacks.onArticlesPerPageChange);
            }
        });
    }

    if (apiEndpointForm) {
        apiEndpointForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (apiUrlInput && chatApiUrlInput) {
                saveApiEndpoints(apiUrlInput.value, chatApiUrlInput.value);
            }
        });
    }

    if (aiPromptsForm) {
        aiPromptsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (summaryPromptInput && chatPromptInput && tagGenerationPromptInput) {
                saveAiPrompts(summaryPromptInput.value, chatPromptInput.value, tagGenerationPromptInput.value);
            }
        });
    }

    if (resetPromptsBtn) {
        resetPromptsBtn.addEventListener('click', resetAiPromptsToDefaults);
    }

    if (globalRssSettingsForm) {
        globalRssSettingsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (rssFetchIntervalInput) {
                saveGlobalRssFetchInterval(rssFetchIntervalInput.value);
            }
        });
    }
    console.log("ConfigManager: Setup form event listeners attached.");
}

console.log("frontend/js/configManager.js: Module loaded.");
