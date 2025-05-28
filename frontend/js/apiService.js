// frontend/js/apiService.js
import { SUMMARIES_API_ENDPOINT, CHAT_API_ENDPOINT_BASE } from './state.js';

/**
 * This module centralizes all API communication for the NewsAI frontend.
 * Each function corresponds to an API endpoint on the backend.
 * It handles making the fetch request and basic error checking.
 */

/**
 * Helper function to handle common fetch logic and JSON parsing.
 * @param {string} url - The URL to fetch.
 * @param {object} options - The options for the fetch request (method, headers, body, etc.).
 * @returns {Promise<object>} - A promise that resolves to the JSON response.
 * @throws {Error} - Throws an error if the network response is not ok, including details from the server if possible.
 */
async function handleFetch(url, options = {}) {
    console.log(`API Service: Fetching ${url} with options:`, options.method || 'GET', options.body ? 'with body' : 'no body');
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            let errorDetail = `HTTP error! status: ${response.status}`;
            try {
                // Try to parse error response from backend if it's JSON
                const errorData = await response.json();
                errorDetail = errorData.detail || JSON.stringify(errorData) || errorDetail;
            } catch (e) {
                // If error response is not JSON, use text
                try {
                    errorDetail = await response.text() || errorDetail;
                } catch (e_text) {
                    // Fallback if text() also fails
                }
            }
            console.error(`API Service: Fetch error for ${url} - ${errorDetail}`);
            throw new Error(errorDetail);
        }
        // Handle 204 No Content responses specifically, as .json() will fail
        if (response.status === 204) {
            console.log(`API Service: Received 204 No Content for ${url}`);
            return null; // Or an empty object, depending on how it's handled
        }
        return response.json();
    } catch (error) {
        console.error(`API Service: Network or unexpected error for ${url}: ${error.message}`, error);
        // Re-throw the error so the calling function can handle it
        throw error;
    }
}

/**
 * Fetches the initial configuration data from the backend.
 * @returns {Promise<object>} Initial configuration data.
 */
export async function fetchInitialConfigData() {
    return handleFetch('/api/initial-config');
}

/**
 * Fetches news summaries based on the provided payload.
 * @param {object} payload - The query parameters for fetching summaries (page, page_size, filters, etc.).
 * @returns {Promise<object>} Paginated summary results.
 */
export async function fetchNewsSummaries(payload) {
    return handleFetch(SUMMARIES_API_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

/**
 * Adds a new RSS feed source.
 * @param {object} feedData - Object containing { url, name (optional), fetch_interval_minutes (optional) }.
 * @returns {Promise<object>} The newly added feed source data.
 */
export async function addRssFeed(feedData) {
    return handleFetch('/api/feeds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(feedData)
    });
}

/**
 * Fetches all configured RSS feed sources from the database.
 * @returns {Promise<Array<object>>} A list of feed sources.
 */
export async function fetchDbFeeds() {
    return handleFetch('/api/feeds');
}

/**
 * Updates an existing RSS feed source.
 * @param {number} feedId - The ID of the feed to update.
 * @param {object} updatePayload - Object containing { name (optional), fetch_interval_minutes (optional) }.
 * @returns {Promise<object>} The updated feed source data.
 */
export async function updateRssFeed(feedId, updatePayload) {
    return handleFetch(`/api/feeds/${feedId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatePayload)
    });
}

/**
 * Deletes an RSS feed source.
 * @param {number} feedId - The ID of the feed to delete.
 * @returns {Promise<null>} Resolves if deletion is successful (204 No Content).
 */
export async function deleteRssFeed(feedId) {
    return handleFetch(`/api/feeds/${feedId}`, {
        method: 'DELETE'
    });
}

/**
 * Triggers a manual refresh of all RSS feeds on the backend.
 * @returns {Promise<object>} A message indicating the refresh has been initiated.
 */
export async function triggerRssRefresh() {
    return handleFetch('/api/trigger-rss-refresh', {
        method: 'POST'
    });
}

/**
 * Regenerates the summary for a specific article.
 * @param {number} articleId - The ID of the article.
 * @param {object} payload - Object containing { custom_prompt (optional), regenerate_tags (optional) }.
 * @returns {Promise<object>} The article data with the regenerated summary.
 */
export async function regenerateSummary(articleId, payload) {
    return handleFetch(`/api/articles/${articleId}/regenerate-summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

/**
 * Fetches the chat history for a specific article.
 * @param {number} articleId - The ID of the article.
 * @returns {Promise<Array<object>>} A list of chat history items.
 */
export async function fetchChatHistory(articleId) {
    // CHAT_API_ENDPOINT_BASE should be '/api' if the endpoint is '/api/article/...'
    return handleFetch(`${CHAT_API_ENDPOINT_BASE}/article/${articleId}/chat-history`);
}

/**
 * Sends a new chat message for an article.
 * @param {object} payload - Object containing { article_id, question, chat_prompt (optional), chat_history (optional) }.
 * @returns {Promise<object>} The AI's response to the chat message.
 */
export async function postChatMessage(payload) {
    // CHAT_API_ENDPOINT_BASE should be '/api' if the endpoint is '/api/chat-with-article'
    return handleFetch(`${CHAT_API_ENDPOINT_BASE}/chat-with-article`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

/**
 * Deletes old article data from the backend.
 * @param {number} daysOld - The minimum age in days for articles to be deleted.
 * @returns {Promise<object>} A message indicating the result of the cleanup operation.
 */
export async function deleteOldData(daysOld) {
    return handleFetch(`/api/admin/cleanup-old-data?days_old=${daysOld}`, {
        method: 'DELETE'
    });
}

console.log("frontend/js/apiService.js: Module loaded.");
