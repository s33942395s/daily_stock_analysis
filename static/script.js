/**
 * 股票智能分析系統 - 前端邏輯
 */

// DOM Elements
const analyzeForm = document.getElementById('analyzeForm');
const stockCodeInput = document.getElementById('stockCode');
const marketBadge = document.getElementById('marketBadge');
const analyzeBtn = document.getElementById('analyzeBtn');
const resultsSection = document.getElementById('resultsSection');
const errorMessage = document.getElementById('errorMessage');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Setup event listeners
    analyzeForm.addEventListener('submit', handleAnalyze);
    stockCodeInput.addEventListener('input', handleCodeInput);

    // Setup quick example buttons
    document.querySelectorAll('.example-tag').forEach(tag => {
        tag.addEventListener('click', () => {
            stockCodeInput.value = tag.dataset.code;
            handleCodeInput();
            analyzeForm.requestSubmit();
        });
    });
});

/**
 * Detect market from stock code
 */
function detectMarket(code) {
    code = code.trim().toUpperCase();

    // Taiwan stock format
    if (code.endsWith('.TW') || code.endsWith('.TWO')) {
        return 'TW';
    }

    // Pure digits 4-6 chars = Taiwan
    if (/^\d{4,6}$/.test(code)) {
        return 'TW';
    }

    // Pure letters 1-5 chars = US
    if (/^[A-Z]{1,5}(\.[A-Z])?$/.test(code)) {
        return 'US';
    }

    return 'AUTO';
}

/**
 * Handle code input change
 */
function handleCodeInput() {
    const code = stockCodeInput.value.trim().toUpperCase();
    const market = detectMarket(code);

    marketBadge.textContent = market === 'US' ? '美股' :
        market === 'TW' ? '台股' : '自動偵測';
    marketBadge.className = 'market-badge ' + market.toLowerCase();
}

/**
 * Handle form submit
 */
async function handleAnalyze(e) {
    e.preventDefault();

    const code = stockCodeInput.value.trim().toUpperCase();
    if (!code) return;

    // Show loading state
    setLoading(true);
    hideError();
    resultsSection.style.display = 'none';

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ code })
        });

        const result = await response.json();

        if (result.success) {
            displayResults(result.data);
        } else {
            showError(result.error || '分析失敗');
        }
    } catch (error) {
        console.error('Analysis error:', error);
        showError('網路錯誤，請稍後再試');
    } finally {
        setLoading(false);
    }
}

/**
 * Display analysis results
 */
function displayResults(data) {
    // Stock header
    document.getElementById('stockName').textContent = data.name || data.code;
    document.getElementById('stockCodeDisplay').textContent = data.code;
    document.getElementById('marketTag').textContent = data.market === 'US' ? '美股' : '台股';

    // Score
    const scoreValue = document.getElementById('scoreValue');
    scoreValue.textContent = data.sentiment_score;
    scoreValue.className = 'score-value ' + getScoreClass(data.sentiment_score);

    // Core analysis
    const adviceBadge = document.getElementById('adviceBadge');
    adviceBadge.textContent = data.operation_advice;
    adviceBadge.className = 'advice-badge ' + getAdviceClass(data.operation_advice);

    document.getElementById('trendText').textContent = data.trend_prediction || '-';
    document.getElementById('logicText').textContent = data.core_logic || '-';

    // Key signals
    const signalList = document.getElementById('signalList');
    signalList.innerHTML = formatList(data.key_signals);

    // Risk warnings
    const riskList = document.getElementById('riskList');
    riskList.innerHTML = formatList(data.risk_warnings);

    // Strategy
    document.getElementById('strategyContent').textContent =
        formatStrategy(data.sniper_strategy);

    // Position
    document.getElementById('positionContent').textContent =
        formatStrategy(data.position_strategy);

    // Checklist
    const checklist = document.getElementById('checklist');
    checklist.innerHTML = formatChecklist(data.checklist);

    // Footer
    document.getElementById('confidence').textContent =
        `置信度: ${data.confidence || '-'}`;
    document.getElementById('timestamp').textContent =
        `分析時間: ${data.analyzed_at || '-'}`;

    // Show results
    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/**
 * Format list items
 */
function formatList(items) {
    if (!items || (Array.isArray(items) && items.length === 0)) {
        return '<li>暫無資料</li>';
    }

    if (typeof items === 'string') {
        return `<li>${escapeHtml(items)}</li>`;
    }

    if (Array.isArray(items)) {
        return items.map(item => `<li>${escapeHtml(item)}</li>`).join('');
    }

    return '<li>暫無資料</li>';
}

/**
 * Format checklist
 */
function formatChecklist(items) {
    if (!items || (Array.isArray(items) && items.length === 0)) {
        return '<li>暫無資料</li>';
    }

    if (typeof items === 'string') {
        return `<li>✓ ${escapeHtml(items)}</li>`;
    }

    if (Array.isArray(items)) {
        return items.map(item => `<li>✓ ${escapeHtml(item)}</li>`).join('');
    }

    return '<li>暫無資料</li>';
}

/**
 * Format strategy object
 */
function formatStrategy(strategy) {
    if (!strategy) return '暫無資料';

    if (typeof strategy === 'string') {
        return strategy;
    }

    if (typeof strategy === 'object') {
        return Object.entries(strategy)
            .map(([key, value]) => `${value}`)
            .join('\n');
    }

    return '暫無資料';
}

/**
 * Get score class based on value
 */
function getScoreClass(score) {
    if (score >= 70) return 'positive';
    if (score <= 40) return 'negative';
    return 'neutral';
}

/**
 * Get advice class
 */
function getAdviceClass(advice) {
    if (!advice) return '';
    const lower = advice.toLowerCase();
    if (lower.includes('買') || lower.includes('buy')) return 'buy';
    if (lower.includes('賣') || lower.includes('sell')) return 'sell';
    return 'hold';
}

/**
 * Set loading state
 */
function setLoading(loading) {
    analyzeBtn.disabled = loading;
    analyzeBtn.querySelector('.button-text').style.display = loading ? 'none' : 'inline';
    analyzeBtn.querySelector('.button-loading').style.display = loading ? 'flex' : 'none';
}

/**
 * Show error message
 */
function showError(message) {
    errorMessage.querySelector('.error-text').textContent = message;
    errorMessage.style.display = 'flex';
}

/**
 * Hide error message
 */
function hideError() {
    errorMessage.style.display = 'none';
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
