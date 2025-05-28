// frontend/js/state.js

/**
 * This module holds the shared frontend state for the NewsAI application.
 * Exported variables can be imported and modified by other modules.
 * It's a simple approach to state management for this application size.
 * For larger applications, a more robust state management library (like Redux, Zustand, or Vuex)
 * might be considered, but for now, direct export/import is sufficient.
 */

// --- Core Application State ---
export let dbFeedSources = []; // Stores the list of RSS feed sources from the database
export let articlesPerPage = 6; // Default number of articles to display per page
export let currentPage = 1; // Current page number for pagination
export let totalPages = 1; // Total number of pages available based on current filters/articles
export let totalArticlesAvailable = 0; // Total articles matching current filters
export let isLoadingMoreArticles = false; // Flag to prevent multiple simultaneous loads during infinite scroll
export let currentArticleForChat = null; // Holds the article data when the chat modal is open
export let currentChatHistory = []; // Stores the chat history for the currently open chat modal session

// --- API Endpoints & Configuration ---
// These can be updated from localStorage or initial config
export let SUMMARIES_API_ENDPOINT = '/api/get-news-summaries';
export let CHAT_API_ENDPOINT_BASE = '/api'; // Base for chat-related endpoints like /chat-with-article and /article/{id}/chat-history

// --- Prompts (Defaults and Current Values) ---
// These will be initialized with defaults and then potentially overridden by localStorage or user settings
export let defaultSummaryPrompt = "Please summarize: {text}";
export let defaultChatPrompt = "Article: {article_text}\nQuestion: {question}\nAnswer:";
export let defaultTagGenerationPrompt = "Generate 3-5 comma-separated tags for: {text}";

export let currentSummaryPrompt = defaultSummaryPrompt;
export let currentChatPrompt = defaultChatPrompt;
export let currentTagGenerationPrompt = defaultTagGenerationPrompt;

export let globalRssFetchInterval = 60; // Default global RSS fetch interval in minutes

// --- Filters ---
export let activeFeedFilterIds = []; // Array of IDs for currently active feed source filters
export let activeTagFilterIds = []; // Array of objects {id: tagId, name: tagName} for active tag filters
export let currentKeywordSearch = null; // Stores the current keyword search term

// --- DOM Element References (Consider moving to a dedicated UI elements module if it grows too large) ---
// It can be useful to have some key, frequently accessed elements here,
// or ensure they are consistently retrieved by UI modules.
// For now, individual modules will grab their own elements.

// --- Utility functions to update state (optional, but can be good practice) ---
// These provide a more controlled way to modify state from other modules.

export function setDbFeedSources(sources) {
    dbFeedSources = Array.isArray(sources) ? sources : [];
}

export function setArticlesPerPage(count) {
    const numCount = parseInt(count);
    if (!isNaN(numCount) && numCount > 0) {
        articlesPerPage = numCount;
    }
}

export function setCurrentPage(page) {
    const numPage = parseInt(page);
    if (!isNaN(numPage) && numPage > 0) {
        currentPage = numPage;
    }
}

export function setTotalPages(pages) {
    const numPages = parseInt(pages);
    if (!isNaN(numPages) && numPages >= 0) {
        totalPages = numPages;
    }
}

export function setTotalArticlesAvailable(count) {
    const numCount = parseInt(count);
    if (!isNaN(numCount) && numCount >= 0) {
        totalArticlesAvailable = numCount;
    }
}

export function setIsLoadingMoreArticles(isLoading) {
    isLoadingMoreArticles = !!isLoading; // Coerce to boolean
}

export function setCurrentArticleForChat(article) {
    currentArticleForChat = article; // Can be an object or null
}

export function setCurrentChatHistory(history) {
    currentChatHistory = Array.isArray(history) ? history : [];
}

export function setApiEndpoints(summariesEndpoint, chatBaseEndpoint) {
    if (summariesEndpoint) SUMMARIES_API_ENDPOINT = summariesEndpoint;
    if (chatBaseEndpoint) CHAT_API_ENDPOINT_BASE = chatBaseEndpoint;
}

export function setDefaultPrompts(summary, chat, tag) {
    if (summary) defaultSummaryPrompt = summary;
    if (chat) defaultChatPrompt = chat;
    if (tag) defaultTagGenerationPrompt = tag;
}

export function setCurrentPrompts(summary, chat, tag) {
    currentSummaryPrompt = summary || defaultSummaryPrompt;
    currentChatPrompt = chat || defaultChatPrompt;
    currentTagGenerationPrompt = tag || defaultTagGenerationPrompt;
}

export function setGlobalRssFetchInterval(interval) {
    const numInterval = parseInt(interval);
    if (!isNaN(numInterval) && numInterval >= 5) { // Assuming a minimum interval
        globalRssFetchInterval = numInterval;
    }
}

export function setActiveFeedFilterIds(ids) {
    activeFeedFilterIds = Array.isArray(ids) ? ids.map(id => parseInt(id)).filter(id => !isNaN(id)) : [];
}

export function setActiveTagFilterIds(tagObjects) {
    // Expects an array of {id: number, name: string}
    activeTagFilterIds = Array.isArray(tagObjects) ? tagObjects.filter(t => t && typeof t.id === 'number' && typeof t.name === 'string') : [];
}
export function addActiveTagFilter(tagObj) {
    if (tagObj && typeof tagObj.id === 'number' && typeof tagObj.name === 'string' && !activeTagFilterIds.some(t => t.id === tagObj.id)) {
        activeTagFilterIds.push(tagObj);
    }
}
export function removeActiveTagFilter(tagId) {
    const numTagId = parseInt(tagId);
    if (!isNaN(numTagId)) {
        activeTagFilterIds = activeTagFilterIds.filter(t => t.id !== numTagId);
    }
}


export function setCurrentKeywordSearch(keyword) {
    currentKeywordSearch = typeof keyword === 'string' ? keyword.trim() : null;
}

// Log initialization
console.log("frontend/js/state.js: Module loaded and state initialized.");

