"""
JS-scripts for inject in browser with Playwright.
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
        /* Send to Python immediately — survives page reload (Playwright expose_function).
           Descriptions are sent later on confirm via same seq (Python handler replaces by seq). */
        if (typeof window.__python_recorder_on_action === 'function') {
            try { window.__python_recorder_on_action(JSON.stringify(action)); } catch(ignored) {}
        }
        if (typeof window.__recorderOnAction === 'function') {
            try { window.__recorderOnAction(action); } catch(ignored) {}
        }
    }

    /* Block event capture while the signature modal/popup is open */
    function _isModalOpen() {
        return document.getElementById('__recorderModal') !== null
            || window.__signerOpen === true;
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
            role === 'listbox' || role === 'combobox' || role === 'tab' ||
            role === 'treeitem' || role === 'gridcell' ||
            target.closest('select') ||
            target.closest('[role="listbox"]') ||
            target.closest('[role="menu"]') ||
            target.closest('[role="combobox"]') ||
            target.closest('[role="tablist"]') ||
            target.onclick ||
            target.closest('[onclick]') ||
            target.closest('button') ||
            target.closest('a[href]') ||
            target.hasAttribute('tabindex') ||
            target.closest('[tabindex]') ||
            (typeof target.onmousedown === 'function') ||
            (typeof target.onmouseup === 'function');
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
        /* Capture API responses linked to recent user actions.
           IMPORTANT: scan backwards for the last USER action (not api_response)
           so that multiple sequential API calls all link to the same user action. */
        var args = arguments;
        var url = (args[0] && args[0].url) ? args[0].url : (args[0] || '');
        var opts = args[1] || {};

        var actions = window.__recordedActions;
        var linkedAction = null;
        for (var _i = actions.length - 1; _i >= 0; _i--) {
            if (actions[_i].type !== 'api_response') {
                linkedAction = actions[_i];
                break;
            }
        }
        var startTime = Date.now();

        return _origFetch.apply(this, args).then(function(response) {
            var endTime = Date.now();
            if (!linkedAction || (startTime - linkedAction.timestamp) > 5000) return response;

            try {
                var clone = response.clone();
                return clone.text().then(function(body) {
                    _push({
                        seq: ++window.__actionId,
                        type: 'api_response',
                        linkedToAction: linkedAction.seq,
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
                linkedToAction: linkedAction ? linkedAction.seq : 0,
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
    var _popup = null;

    function _markSignerOpen() {
        window.__signerOpen = true;
    }

    function _markSignerClosed() {
        /* Delay clearing the flag so residual click events from popup
           close don't get recorded as new actions. */
        setTimeout(function() { window.__signerOpen = false; }, 300);
    }

    /* ---- Build signer HTML for popup window ---- */

    function _buildSignerHTML(action) {
        var actionTypeLabel = action.type === 'click' ? 'click' :
            action.type === 'submit' ? 'form submit' :
            action.type === 'input_enter' ? 'text input' : action.type;
        var elementInfo = _escH((action.elementText||action.element||'element').slice(0,60));
        var defaultAnswer = action.type === 'click' ? 'Clicked on '+elementInfo :
            (action.type==='submit'?'Submitted form':'Entered text');
        var pageUrl = _escH((action.pageUrl||'').slice(0,80));
        var badgeColor = action.type==='click'?'#e94560':action.type==='submit'?'#f5a623':'#4a90d9';

        return '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Sign Action</title><style>'
            +'*{margin:0;padding:0;box-sizing:border-box}'
            +'body{font:14px/1.5 sans-serif;background:#1a1a2e;color:#e0e0e0;padding:24px 28px;width:460px}'
            +'.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}'
            +'.title{color:#e94560;font-weight:bold;font-size:16px}'
            +'.badge{color:#fff;border-radius:4px;padding:2px 10px;font-size:12px;font-weight:600}'
            +'.info{background:#16213e;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:13px;word-break:break-word}'
            +'.info label{color:#aaa;display:block}.info span{color:#e0e0e0}.info .url{font-size:12px}'
            +'.field-label{display:block;font-size:13px;color:#aaa;margin-bottom:4px}'
            +'.field-label .hint{color:#666}'
            +'input[type=text]{width:100%;padding:10px 12px;border:1px solid #2a2a4a;border-radius:6px;'
            +'background:#0f0f23;color:#e0e0e0;font:13px/1.4 sans-serif;margin-bottom:12px;outline:none}'
            +'input[type=text]:focus{border-color:#e94560}'
            +'.btns{display:flex;justify-content:flex-end;gap:10px;margin-top:6px}'
            +'.btn-skip{padding:8px 16px;border:1px solid #333;border-radius:6px;background:transparent;color:#888;cursor:pointer;font-size:13px}'
            +'.btn-ok{padding:8px 20px;border:none;border-radius:6px;background:#e94560;color:#fff;cursor:pointer;font-weight:600;font-size:13px}'
            +'</style></head><body>'
            +'<div class="header"><div class="title">&#x270D;&#xFE0F; Sign Action</div>'
            +'<span class="badge" style="background:'+badgeColor+'">'+actionTypeLabel+'</span></div>'
            +'<div class="info"><label>Element: <span>'+elementInfo+'</span></label>'
            +(pageUrl?'<label class="url">URL: <span>'+pageUrl+'</span></label>':'')
            +'</div>'
            +'<label class="field-label">1/2. What did you do?</label>'
            +'<input id="d1" type="text" value="'+_escAttr(defaultAnswer)+'" autofocus>'
            +'<label class="field-label">2/2. What happened? <span class="hint">(result, new content, error)</span></label>'
            +'<input id="d2" type="text" placeholder="e.g. response appeared, page loaded...">'
            +'<div class="btns">'
            +'<button id="skip" class="btn-skip">Skip</button>'
            +'<button id="ok" class="btn-ok">&#x2714; Confirm</button>'
            +'</div>'
            +'<script>'
            +'var d1=document.getElementById("d1"),d2=document.getElementById("d2");'
            +'function send(desc1,desc2){'
            +'if(window.opener&&!window.opener.closed){window.opener.postMessage({d1:desc1,d2:desc2},"*");}'
            +'window.close();'
            +'}'
            +'document.getElementById("ok").onclick=function(){send(d1.value.trim(),d2.value.trim());};'
            +'document.getElementById("skip").onclick=function(){send("","");};'
            +'d1.onkeydown=function(e){if(e.key==="Enter"){e.preventDefault();d2.focus();}};'
            +'d2.onkeydown=function(e){if(e.key==="Enter"){e.preventDefault();send(d1.value.trim(),d2.value.trim());}};'
            +'document.body.addEventListener("keydown",function(e){'
            +'if(e.key==="Escape"){send("","");return;}'
            +'if(e.key==="Tab"){'
            +'var all=document.querySelectorAll("input,button");'
            +'var f=all[0],l=all[all.length-1];'
            +'if(e.shiftKey&&document.activeElement===f){e.preventDefault();l.focus();}'
            +'else if(!e.shiftKey&&document.activeElement===l){e.preventDefault();f.focus();}'
            +'}'
            +'});'
            +'<\/script></body></html>';
    }

    /* ---- Popup lifecycle ---- */

    function _closePopup() {
        if (_popup && !_popup.closed) {
            try { _popup.close(); } catch(ignored) {}
        }
        _popup = null;
        window.removeEventListener('message', _onPopupMessage);
        _markSignerClosed();
    }

    function _onPopupMessage(e) {
        if (!_popup) return;
        if (e.source !== _popup) return;
        var data = e.data;
        if (typeof data !== 'object' || !('d1' in data)) return;

        var desc1 = data.d1 || '';
        var desc2 = data.d2 || '';
        var cb = _popup._callback;
        _closePopup();
        if (cb) cb(desc1, desc2);
    }

    function _openSigner(action, onConfirm) {
        _closePopup();

        /* Open popup with minimal initial size; auto-resize after content renders. */
        var w = 480, h = 380;
        var left = Math.max(0, (screen.width - w) / 2);
        var top = Math.max(0, (screen.height - h) / 3);

        _popup = window.open('about:blank', '_blank',
            'width='+w+',height='+h+',left='+left+',top='+top
            +',menubar=no,toolbar=no,location=no,status=no,scrollbars=no');
        if (!_popup) {
            /* Popup blocked — fall back to iframe approach */
            onConfirm('', '');
            return;
        }
        _popup._callback = onConfirm;

        /* Listen for messages from popup */
        window.addEventListener('message', _onPopupMessage);

        /* Write signer content */
        var doc = _popup.document;
        doc.open();
        doc.write(_buildSignerHTML(action));
        doc.close();

        /* Auto-size popup to fit content (after render) */
        setTimeout(function() {
            try {
                var b = _popup.document.body;
                var h = _popup.document.documentElement;
                var cw = Math.max(b.scrollWidth, b.offsetWidth, h.clientWidth);
                var ch = Math.max(b.scrollHeight, b.offsetHeight, h.clientHeight);
                _popup.resizeTo(Math.max(cw + 16, 460), Math.max(ch + 16, 340));
            } catch(ignored) {}
        }, 10);

        /* Focus the popup */
        try { _popup.focus(); } catch(ignored) {}

        /* Mark signer as open (prevents action recording in main window) */
        _markSignerOpen();
    }

    /* ---- Escapers ---- */

    function _escH(s) {
        if (!s) return '';
        return (''+s).replace(/&/g,'\x26amp;').replace(/</g,'\x26lt;').replace(/>/g,'\x26gt;').replace(/"/g,'\x26quot;');
    }
    function _escAttr(s) {
        if (!s) return '';
        return (''+s).replace(/&/g,'\x26amp;').replace(/"/g,'\x26quot;').replace(/'/g,'\x26#39;');
    }

    /* ---- Action handler ---- */

    var _pendingQueue = [];

    window.__recorderOnAction = function(action) {
        if (action.type === 'api_response') return _origOnAction(action);
        if (_popup && !_popup.closed) { _pendingQueue.push(action); return; }

        /* Open popup IMMEDIATELY (while still in user-gesture context).
           The site will process the click after we return — its dialog
           opens in the MAIN window, our signer opens in a SEPARATE popup.
           They cannot interfere with each other. */
        _openSigner(action, function(desc1, desc2) {
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

            /* Send updated action (with descriptions) to Python — replaces draft by seq.
               If skipped, send action with skipped flag so Python can filter it out. */
            if (typeof window.__python_recorder_on_action === 'function') {
                if (desc1 !== '' || desc2 !== '') {
                    try { window.__python_recorder_on_action(JSON.stringify(action)); } catch(ignored) {}
                } else {
                    /* User skipped — mark as skipped so Python handler can remove it */
                    action.skipped = true;
                    try { window.__python_recorder_on_action(JSON.stringify(action)); } catch(ignored) {}
                }
            }

            if (_pendingQueue.length > 0) {
                var next = _pendingQueue.shift();
                window.__recorderOnAction(next);
            }
        });
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
