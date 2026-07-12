"""
JS-скрипты для инжекции в браузер через Playwright.
"""

_CAPTURE_SCRIPT = r"""
(function() {
    if (window.__recorderInstalled) return;
    window.__recorderInstalled = true;

    window.__recordedActions = [];
    window.__actionId = 0;
    window.__recorderReady = false;

    var _panel = null;
    var _statsEl = null;
    var _lastEl = null;

    /* Deferred panel init — body may not exist when add_init_script runs */
    function _initPanel() {
        if (document.body) {
            _panel = document.createElement('div');
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
            _statsEl = document.getElementById('__recorderStats');
            _lastEl = document.getElementById('__recorderLast');
            window.__recorderReady = true;
        } else {
            setTimeout(_initPanel, 50);
        }
    }

    function _updatePanel(action) {
        if (!window.__recorderReady) return;
        if (action.type === 'api_response') return;
        var userCount = 0;
        for (var i = 0; i < window.__recordedActions.length; i++) {
            if (window.__recordedActions[i].type !== 'api_response') userCount++;
        }
        _statsEl.textContent = 'Actions: ' + userCount;
        var label = (action.elementText || action.element || '?').slice(0, 40);
        _lastEl.textContent = action.type + ': ' + label;
    }

    /* Expose panel updater so _PROMPT_SCRIPT can refresh it on skip */
    window.__recorderUpdatePanel = function() {
        if (!window.__recorderReady) return;
        var userCount = 0;
        for (var i = 0; i < window.__recordedActions.length; i++) {
            if (window.__recordedActions[i].type !== 'api_response') userCount++;
        }
        _statsEl.textContent = 'Actions: ' + userCount;
    };

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
        if (typeof window.__python_recorder_on_action === 'function') {
            try { window.__python_recorder_on_action(JSON.stringify(action)); } catch(ignored) {}
        }
        if (typeof window.__recorderOnAction === 'function') {
            try { window.__recorderOnAction(action); } catch(ignored) {}
        }
    }

    /* Block event capture while the signature modal is open */
    function _isModalOpen() {
        return document.getElementById('__recorderModal') !== null;
    }

    document.addEventListener('click', function(e) {
        if (_isModalOpen()) return;
        if (window.getSelection() && window.getSelection().toString()) return;
        var target = e.target;
        var tag = (target.tagName || '').toLowerCase();
        var type = (target.type || '').toLowerCase();

        var interactive = ['a','button','input','select','textarea','summary','option','optgroup'];
        var role = target.getAttribute('role') || '';
        var isClickable = interactive.indexOf(tag) !== -1 ||
            role === 'button' || role === 'link' ||
            role === 'option' || role === 'menuitem' ||
            role === 'menuitemcheckbox' || role === 'menuitemradio' ||
            target.closest('select') ||
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
        if (_isModalOpen()) return;
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
        if (_isModalOpen()) return;
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
        /* Still capture API responses even when modal is open,
           but don't link to the wrong action if modal is blocking */
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
    /* Start deferred panel init (body may not exist yet) */
    _initPanel();
    /* Fallback: re-init on DOMContentLoaded if not ready */
    document.addEventListener('DOMContentLoaded', function() {
        if (!window.__recorderReady) _initPanel();
    });
})();
"""

# Playwright (headless). Modal HTML-overlay works everywhere.
_PROMPT_SCRIPT = r"""
(function() {
    if (window.__recorderPromptInstalled) return;
    window.__recorderPromptInstalled = true;

    var _origOnAction = window.__recorderOnAction || function() {};
    var _overlay = null;
    var _activeCallback = null;

    var _focusBlockers = null;
    var _eventGuard = null;

    function _installFocusBlockers() {
        if (_focusBlockers) return;
        function _blockFocusLeak(e) {
            if (!_overlay) return;
            var related = e.relatedTarget;
            if (related && _overlay.contains(related) && !_overlay.contains(e.target)) {
                e.stopPropagation();
                e.stopImmediatePropagation();
            }
        }
        document.addEventListener('focusout', _blockFocusLeak, true);
        document.addEventListener('blur', _blockFocusLeak, true);
        _focusBlockers = { focusout: _blockFocusLeak, blur: _blockFocusLeak };
    }

    function _removeFocusBlockers() {
        if (!_focusBlockers) return;
        document.removeEventListener('focusout', _focusBlockers.focusout, true);
        document.removeEventListener('blur', _focusBlockers.blur, true);
        _focusBlockers = null;
    }

    /* Event guard on window (capture) — fires BEFORE document-level handlers.
       Prevents page modal/popup capture handlers from swallowing clicks on our signer. */
    function _installEventGuard() {
        if (_eventGuard) return;
        function _guard(e) {
            if (!_overlay) return;
            /* elementFromPoint uses visual stacking — our modal is topmost */
            var target = document.elementFromPoint(e.clientX, e.clientY);
            if (target && _overlay.contains(target)) {
                /* This event belongs to our modal — stop page handlers from seeing it */
                e.stopPropagation();
            }
        }
        window.addEventListener('mousedown', _guard, true);
        window.addEventListener('pointerdown', _guard, true);
        window.addEventListener('touchstart', _guard, true);
        _eventGuard = { mousedown: _guard, pointerdown: _guard, touchstart: _guard };
    }

    function _removeEventGuard() {
        if (!_eventGuard) return;
        window.removeEventListener('mousedown', _eventGuard.mousedown, true);
        window.removeEventListener('pointerdown', _eventGuard.pointerdown, true);
        window.removeEventListener('touchstart', _eventGuard.touchstart, true);
        _eventGuard = null;
    }

    function _closeModal() {
        if (_overlay) {
            _overlay.parentNode.removeChild(_overlay);
            _overlay = null;
            _activeCallback = null;
        }
        _removeFocusBlockers();
        _removeEventGuard();
    }

    function _showModal(action, onConfirm) {
        _closeModal();
        _installFocusBlockers();
        _installEventGuard();

        var actionTypeLabel = action.type === 'click' ? 'click' :
                              action.type === 'submit' ? 'form submit' :
                              action.type === 'input_enter' ? 'text input' :
                              action.type;

        var elementInfo = (action.elementText || action.element || 'element').slice(0, 60);
        var defaultAnswer = action.type === 'click'
            ? 'Clicked on ' + elementInfo
            : (action.type === 'submit' ? 'Submitted form' : 'Entered text');
        var pageUrl = (action.pageUrl || '').slice(0, 80);

        var el = document.createElement('div');
        el.id = '__recorderModal';
        el.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;'
            + 'z-index:2147483646;background:rgba(0,0,0,0.55);'
            + 'display:flex;align-items:center;justify-content:center;';
        el.innerHTML =
            '<div style="background:#1a1a2e;color:#e0e0e0;border:1px solid #e94560;'
                + 'border-radius:12px;padding:24px 28px;font:14px/1.5 sans-serif;'
                + 'min-width:420px;max-width:520px;box-shadow:0 8px 40px rgba(0,0,0,0.6);">'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
            + '<div style="color:#e94560;font-weight:bold;font-size:16px;">&#x270D;&#xFE0F; Sign Action #' + action.seq + '</div>'
            + '<span class="__recorderModalBadge" style="background:' + (action.type === 'click' ? '#e94560' : action.type === 'submit' ? '#f5a623' : '#4a90d9') + ';color:#fff;border-radius:4px;padding:2px 10px;font-size:12px;font-weight:600;">' + actionTypeLabel + '</span>'
            + '</div>'
            + '<div style="background:#16213e;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:13px;word-break:break-word;">'
            + '<div style="color:#aaa;margin-bottom:4px;">Element: <span style="color:#e0e0e0;">' + _escHtml(elementInfo) + '</span></div>'
            + (pageUrl ? '<div style="color:#aaa;">URL: <span style="color:#e0e0e0;font-size:12px;">' + _escHtml(pageUrl) + '</span></div>' : '')
            + '</div>'
            + '<label style="display:block;font-size:13px;color:#aaa;margin-bottom:4px;">1/2. What did you do?</label>'
            + '<input id="__recorderDesc1" type="text" value="' + _escAttr(defaultAnswer) + '"'
                + 'style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #2a2a4a;border-radius:6px;'
                + 'background:#0f0f23;color:#e0e0e0;font:13px/1.4 sans-serif;margin-bottom:12px;outline:none;">'
            + '<label style="display:block;font-size:13px;color:#aaa;margin-bottom:4px;">2/2. What happened? <span style="color:#666;">(result, new content, error)</span></label>'
            + '<input id="__recorderDesc2" type="text" placeholder="e.g. response appeared, page loaded..."'
                + 'style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #2a2a4a;border-radius:6px;'
                + 'background:#0f0f23;color:#e0e0e0;font:13px/1.4 sans-serif;margin-bottom:18px;outline:none;">'
            + '<div style="display:flex;justify-content:flex-end;gap:10px;">'
            + '<button id="__recorderModalSkip" style="padding:8px 16px;border:1px solid #333;border-radius:6px;background:transparent;color:#888;cursor:pointer;font-size:13px;">Skip</button>'
            + '<button id="__recorderModalConfirm" style="padding:8px 20px;border:none;border-radius:6px;background:#e94560;color:#fff;cursor:pointer;font-weight:600;font-size:13px;">&#x2714; Confirm</button>'
            + '</div>'
            + '</div></div>';

        document.body.appendChild(el);
        _overlay = el;

        /* Stop all mouse/pointer events on modal from reaching page dropdown handlers */
        ['click','mousedown','mouseup','pointerdown','pointerup','touchstart','touchend'].forEach(function(evt) {
            el.addEventListener(evt, function(e) { e.stopPropagation(); });
        });

        /* Prevent focus from leaving page elements when clicking non-input parts of modal */
        el.addEventListener('mousedown', function(e) {
            var tag = (e.target.tagName || '').toLowerCase();
            if (tag !== 'input' && tag !== 'textarea') {
                e.preventDefault();
            }
        }, true);

        var inp1 = document.getElementById('__recorderDesc1');
        var inp2 = document.getElementById('__recorderDesc2');

        document.getElementById('__recorderModalConfirm').addEventListener('click', function() {
            var d1 = inp1.value.trim();
            var d2 = inp2.value.trim();
            _closeModal();
            onConfirm(d1, d2);
        });

        document.getElementById('__recorderModalSkip').addEventListener('click', function() {
            _closeModal();
            onConfirm('', '');
        });

    }

    function _escHtml(s) {
        if (!s) return '';
        return ('' + s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function _escAttr(s) {
        if (!s) return '';
        return ('' + s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    var _pendingQueue = [];

    window.__recorderOnAction = function(action) {
        if (action.type === 'api_response') {
            return _origOnAction(action);
        }

        if (_overlay) {
            _pendingQueue.push(action);
            return;
        }

        /* Defer modal — let the page process the event first (dropdown open, etc.) */
        setTimeout(function() {
            _showModal(action, function(desc1, desc2) {
                /* Skip = remove action from recording entirely */
                if (desc1 === '' && desc2 === '') {
                    var idx = window.__recordedActions.indexOf(action);
                    if (idx !== -1) window.__recordedActions.splice(idx, 1);
                    if (typeof window.__recorderUpdatePanel === 'function') {
                        window.__recorderUpdatePanel();
                    }
                } else {
                    action.userDescription = desc1;
                    action.resultDescription = desc2;
                }
                _origOnAction(action);

                /* Sync the updated action (with descriptions) to Python.
                   Skip case: don't re-send (already sent raw from _push) */
                if (typeof window.__python_recorder_on_action === 'function') {
                    if (desc1 !== '' || desc2 !== '') {
                        try { window.__python_recorder_on_action(JSON.stringify(action)); } catch(ignored) {}
                    }
                }

                if (_pendingQueue.length > 0) {
                    var next = _pendingQueue.shift();
                    window.__recorderOnAction(next);
                }
            });
        }, 0);
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
