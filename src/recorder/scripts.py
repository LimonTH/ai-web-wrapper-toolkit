"""
JS-скрипты для инжекции в браузер через Playwright.
"""

_CAPTURE_SCRIPT = r"""
(function() {
    if (window.__recorderInstalled) return;
    window.__recorderInstalled = true;

    window.__recordedActions = [];
    window.__actionId = 0;

    var _panel = document.createElement('div');
    _panel.id = '__recorderPanel';
    _panel.innerHTML = '<div style="'
        + 'position:fixed;bottom:16px;right:16px;z-index:2147483647;'
        + 'background:#1a1a2e;color:#e0e0e0;border:1px solid #e94560;'
        + 'border-radius:10px;padding:10px 14px;font:12px/1.4 monospace;'
        + 'min-width:220px;max-width:300px;box-shadow:0 4px 20px rgba(233,69,96,.4);'
        + 'pointer-events:none;user-select:none;'
        + '">'
        + '<div style="color:#e94560;font-weight:bold;margin-bottom:4px;">&#x1F3AC; RECORDING</div>'
        + '<div id="__recorderStats" style="font-size:11px;">Actions: 0</div>'
        + '<div id="__recorderLast" style="font-size:10px;color:#999;margin-top:2px;max-height:36px;overflow:hidden;"></div>'
        + '</div>';
    document.body.appendChild(_panel);

    var _statsEl = document.getElementById('__recorderStats');
    var _lastEl = document.getElementById('__recorderLast');

    function _updatePanel(action) {
        if (action.type === 'api_response') return;
        var userCount = 0;
        for (var i = 0; i < window.__recordedActions.length; i++) {
            if (window.__recordedActions[i].type !== 'api_response') userCount++;
        }
        _statsEl.textContent = 'Actions: ' + userCount;
        var label = (action.elementText || action.element || '?').slice(0, 40);
        _lastEl.textContent = action.type + ': ' + label;
    }

    function _getSelector(el) {
        if (!el || el === document.body) return 'body';
        if (el.id) return '#' + el.id;
        var path = [];
        while (el && el !== document.body) {
            var selector = el.tagName.toLowerCase();
            if (el.id) { path.unshift('#' + el.id); break; }
            if (el.className && typeof el.className === 'string') {
                var cls = el.className.trim().split(/\s+/).slice(0, 2).join('.');
                if (cls) selector += '.' + cls;
            }
            path.unshift(selector);
            el = el.parentElement;
        }
        return path.join(' > ');
    }

    function _push(action) {
        window.__recordedActions.push(action);
        _updatePanel(action);
        if (typeof window.__recorderOnAction === 'function') {
            try { window.__recorderOnAction(action); } catch(ignored) {}
        }
    }

    document.addEventListener('click', function(e) {
        if (window.getSelection() && window.getSelection().toString()) return;
        var target = e.target;
        var tag = (target.tagName || '').toLowerCase();
        var type = (target.type || '').toLowerCase();

        var interactive = ['a','button','input','select','textarea','summary'];
        var isClickable = interactive.indexOf(tag) !== -1 ||
            target.getAttribute('role') === 'button' ||
            target.getAttribute('role') === 'link' ||
            target.onclick ||
            target.closest('[onclick]') ||
            target.closest('button') ||
            target.closest('a[href]');
        if (!isClickable) return;

        var seq = ++window.__actionId;
        var text = (target.innerText || '').trim().slice(0,200) ||
                   (target.value || '').trim().slice(0,200) ||
                   (target.placeholder || '').trim().slice(0,200) ||
                   target.getAttribute('aria-label') || tag;
        var href = target.href || (target.closest('a') || {}).href || '';

        _push({
            seq: seq,
            type: 'click',
            element: tag,
            elementText: text,
            href: href,
            selector: _getSelector(target),
            pageUrl: location.href,
            timestamp: Date.now()
        });
    }, true);

    document.addEventListener('submit', function(e) {
        var seq = ++window.__actionId;
        var form = e.target;
        var data = {};
        try {
            var fd = new FormData(form);
            fd.forEach(function(v,k) { data[k] = (v||'').toString().slice(0,500); });
        } catch(ignored) {}

        _push({
            seq: seq,
            type: 'submit',
            element: 'form',
            elementText: form.getAttribute('aria-label') || form.id || 'form',
            formData: data,
            action: form.action || '',
            selector: _getSelector(form),
            pageUrl: location.href,
            timestamp: Date.now()
        });
    }, true);

    document.addEventListener('keydown', function(e) {
        if (e.key !== 'Enter' || e.shiftKey) return;
        var target = e.target;
        var tag = (target.tagName || '').toLowerCase();
        if (tag !== 'input' && tag !== 'textarea') return;
        if (target.closest('form')) return;

        var seq = ++window.__actionId;
        _push({
            seq: seq,
            type: 'input_enter',
            element: tag,
            elementText: target.placeholder || target.name || tag,
            inputValue: (target.value || '').slice(0,500),
            selector: _getSelector(target),
            pageUrl: location.href,
            timestamp: Date.now()
        });
    }, true);

    var _origFetch = window.fetch;
    window.fetch = function() {
        var args = arguments;
        var url = (args[0] && args[0].url) ? args[0].url : (args[0] || '');
        var opts = args[1] || {};

        var actions = window.__recordedActions;
        var lastAction = actions.length > 0 ? actions[actions.length - 1] : null;
        var startTime = Date.now();

        return _origFetch.apply(this, args).then(function(response) {
            var endTime = Date.now();
            if (!lastAction || (startTime - lastAction.timestamp) > 5000) return response;

            try {
                var clone = response.clone();
                return clone.text().then(function(body) {
                    _push({
                        seq: ++window.__actionId,
                        type: 'api_response',
                        linkedToAction: lastAction.seq,
                        requestMethod: opts.method || 'GET',
                        requestUrl: url,
                        requestBody: opts.body ? (opts.body||'').toString().slice(0,2000) : null,
                        responseStatus: response.status,
                        responseHeaders: (function(h) {
                            var r = {}; h.forEach(function(v,k) { r[k]=v; }); return r;
                        })(response.headers),
                        responseBody: (body||'').slice(0,10000),
                        pageUrl: location.href,
                        timestamp: endTime
                    });
                    return response;
                }, function() { return response; });
            } catch(e) {
                return response;
            }
        }, function(err) {
            _push({
                seq: ++window.__actionId,
                type: 'api_response',
                linkedToAction: lastAction ? lastAction.seq : 0,
                requestMethod: opts.method || 'GET',
                requestUrl: url,
                requestBody: opts.body ? (opts.body||'').toString().slice(0,2000) : null,
                responseStatus: 0,
                responseError: (err && err.message) ? err.message.slice(0,500) : 'fetch failed',
                pageUrl: location.href,
                timestamp: Date.now()
            });
            return Promise.reject(err);
        });
    };

    window.__recorderOnAction = function() {};
})();
"""

_PROMPT_SCRIPT = r"""
(function() {
    if (window.__recorderPromptInstalled) return;
    window.__recorderPromptInstalled = true;

    var _origOnAction = window.__recorderOnAction || function() {};

    window.__recorderOnAction = function(action) {
        if (action.type === 'api_response') {
            return _origOnAction(action);
        }

        var actionTypeLabel = action.type === 'click' ? 'клик' :
                              action.type === 'submit' ? 'отправка формы' :
                              action.type === 'input_enter' ? 'ввод текста' :
                              action.type;

        var elementInfo = (action.elementText || action.element || 'элемент').slice(0, 50);
        var defaultAnswer = action.type === 'click'
            ? 'Нажал на ' + elementInfo
            : (action.type === 'submit' ? 'Отправил форму' : 'Ввёл текст');

        var desc1 = '';
        try {
            desc1 = prompt(
                '[Действие #' + action.seq + '] ' + actionTypeLabel + ' на "' + elementInfo + '"' +
                '\n\n1/2: Что вы сейчас сделали?',
                defaultAnswer
            );
        } catch(e) { desc1 = ''; }
        if (desc1 === null) desc1 = '';

        var desc2 = '';
        try {
            desc2 = prompt(
                '[Действие #' + action.seq + '] ' + actionTypeLabel + ' на "' + elementInfo + '"' +
                '\n\n2/2: Что произошло в ответ?' +
                '\n(какой результат? новый контент? ошибка?)',
                ''
            );
        } catch(e) { desc2 = ''; }
        if (desc2 === null) desc2 = '';

        action.userDescription = desc1;
        action.resultDescription = desc2;

        return _origOnAction(action);
    };
})();
"""


def get_capture_script() -> str:
    return _CAPTURE_SCRIPT


def get_prompt_script() -> str:
    return _PROMPT_SCRIPT


def get_full_script(with_prompts: bool = True) -> str:
    if with_prompts:
        return _CAPTURE_SCRIPT + "\n" + _PROMPT_SCRIPT
    return _CAPTURE_SCRIPT