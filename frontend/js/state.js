// frontend/js/state.js

/**
 * This module holds the shared frontend state for the NewsAI application.
 * Exported variables are 'live bindings' but should generally be modified
 * via exported setter functions to maintain clarity and control.
 */

// --- Core Application State ---
export let dbFeedSources = []; 
export let articlesPerPage = 6; 
export let currentPage = 1; 
export let totalPages = 1; 
export let totalArticlesAvailable = 0; 
export let isLoadingMoreArticles = false; 
export let currentArticleForChat = null; 
export let currentChatHistory = []; 

// For polling
export let lastKnownLatestArticleTimestamp = null; // Stores ISO string

// --- API Endpoints & Configuration ---
// Default values. These will be updated by configManager.js from localStorage or backend initial config.
// The backend route for summaries was changed to /api/articles/summaries
export let SUMMARIES_API_ENDPOINT = '/api/articles/summaries'; 
export let CHAT_API_ENDPOINT_BASE = '/api'; 

// --- Prompts (Defaults and Current Values) ---
export let defaultSummaryPrompt = "Task:Generate a concise, narrative summary of the following article. The output must be Markdown-formatted, engaging, and suitable for a news digest. Focus on the key information, main actors, outcomes, and any significant implications. Ensure the summary flows well and captures the essence of the article. Avoid overly technical jargon unless essential and explained. Structure with a clear beginning, middle, and end. {text}";
export let defaultChatPrompt = "Persona & Goal:You are an insightful AI analyst and conversational partner. Your purpose is to help the user explore the provided article's content in greater depth, moving beyond the initial summary. Engage with their questions thoughtfully, provide detailed explanations, clarify complexities, and offer different perspectives based *only* on the article text. If the user asks for information outside the article, politely state that you can only discuss the provided text. Formatting: Use Markdown for all responses, including bolding, italics, bullet points, and numbered lists where appropriate to enhance readability and structure. Ensure your answers are well-organized and easy to follow. Task: Given the article text below, and the user's question, provide a comprehensive and helpful answer. Article Text: {article_text} Question: {question} Answer (in Markdown):";
export let defaultTagGenerationPrompt = "Given the following article text, generate a list of 3-5 relevant keywords or tags. These tags should be concise, lowercase, and accurately reflect the main topics, entities, or themes of the article. Output them as a comma-separated list. For example: 'ukraine, military aid, international relations, defense policy, us politics'. Article: {text} Tags:";

export let currentSummaryPrompt = defaultSummaryPrompt;
export let currentChatPrompt = defaultChatPrompt;
export let currentTagGenerationPrompt = defaultTagGenerationPrompt;

export let globalRssFetchInterval = 60; 

// --- Filters ---
export let activeFeedFilterIds = []; 
export let activeTagFilterIds = []; 
export let currentKeywordSearch = null; 

// --- Utility functions to update state ---

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
    isLoadingMoreArticles = !!isLoading; 
}

export function setCurrentArticleForChat(article) {
    currentArticleForChat = article; 
}

export function setCurrentChatHistory(history) {
    currentChatHistory = Array.isArray(history) ? history : [];
}

/**
 * Sets the API endpoint URLs in the state.
 * @param {string} summariesEndpoint - The new endpoint for summaries.
 * @param {string} chatBaseEndpoint - The new base endpoint for chat.
 */
export function setApiEndpoints(summariesEndpoint, chatBaseEndpoint) {
    if (typeof summariesEndpoint === 'string' && summariesEndpoint.trim() !== '') {
        SUMMARIES_API_ENDPOINT = summariesEndpoint.trim();
        console.log("State: SUMMARIES_API_ENDPOINT updated to:", SUMMARIES_API_ENDPOINT);
    }
    if (typeof chatBaseEndpoint === 'string' && chatBaseEndpoint.trim() !== '') {
        CHAT_API_ENDPOINT_BASE = chatBaseEndpoint.trim();
        console.log("State: CHAT_API_ENDPOINT_BASE updated to:", CHAT_API_ENDPOINT_BASE);
    }
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
    if (!isNaN(numInterval) && numInterval >= 5) { 
        globalRssFetchInterval = numInterval;
    }
}

export function setActiveFeedFilterIds(ids) {
    activeFeedFilterIds = Array.isArray(ids) ? ids.map(id => parseInt(id)).filter(id => !isNaN(id)) : [];
}

export function setActiveTagFilterIds(tagObjects) {
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

export function setLastKnownLatestArticleTimestamp(timestamp) {
    if (timestamp && typeof timestamp === 'string') {
        try {
            new Date(timestamp); 
            lastKnownLatestArticleTimestamp = timestamp;
        } catch (e) {
            console.error("State: Invalid timestamp provided for lastKnownLatestArticleTimestamp", timestamp, e);
        }
    } else if (timestamp === null) {
        lastKnownLatestArticleTimestamp = null;
    } else {
        console.warn("State: Attempted to set invalid lastKnownLatestArticleTimestamp", timestamp);
    }
}

console.log("frontend/js/state.js: Module loaded and state initialized.");
