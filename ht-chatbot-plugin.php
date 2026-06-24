<?php
/**
 * Plugin Name: HT LMS Chatbot
 * Description: Floating AI chatbot widget connected to FastAPI backend, with lesson ingestion.
 * Version: 1.3
 */

// ─────────────────────────────────────────────────────────────────────────────
// 1. DATA SENDER: Sends lesson data to FastAPI when an instructor updates a lesson
// ─────────────────────────────────────────────────────────────────────────────
add_action('save_post', 'ht_sync_lesson_to_fastapi', 10, 3);
function ht_sync_lesson_to_fastapi($post_id, $post, $update) {
    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) return;
    if (!in_array($post->post_status, ['publish', 'private'])) return;
    if ($post->post_type !== 'post') return; // Adjust to 'lesson' if using a Custom Post Type

    // ── Extract video context BEFORE stripping tags ──────────────────────────
    $video_context = '';

    // Detect YouTube embeds (iframe or shortcode URLs)
    preg_match_all(
        '/(?:youtube\.com\/embed\/|youtu\.be\/|youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})/',
        $post->post_content,
        $yt_matches
    );
    if (!empty($yt_matches[1])) {
        $video_ids = array_unique($yt_matches[1]);
        $video_context .= "\n[Note: This lesson contains " . count($video_ids) . " embedded YouTube video(s). Video ID(s): " . implode(', ', $video_ids) . ". You cannot watch these, but acknowledge they exist if asked.]";
    }

    // Detect HTML5 <video> tags
    preg_match_all('/<video[^>]+src=["\']([^"\']+)["\']/i', $post->post_content, $vid_matches);
    if (!empty($vid_matches[1])) {
        $video_context .= "\n[Note: This lesson contains an embedded HTML5 video file(s): " . implode(', ', $vid_matches[1]) . "]";
    }

    // Detect [video] shortcodes
    if (has_shortcode($post->post_content, 'video')) {
        preg_match_all('/\[video[^\]]*src=["\']([^"\']+)["\']/i', $post->post_content, $sc_matches);
        if (!empty($sc_matches[1])) {
            $video_context .= "\n[Note: This lesson contains a WordPress video shortcode. Source: " . implode(', ', $sc_matches[1]) . "]";
        }
    }
    // ─────────────────────────────────────────────────────────────────────────

    $clean_text = wp_strip_all_tags(strip_shortcodes($post->post_content));
    $clean_text = str_replace("\r\n", "\n", $clean_text);   // normalize Windows line endings
    $clean_text = preg_replace('/\n{3,}/', "\n\n", $clean_text); // collapse 3+ newlines → max 2
    $clean_text = trim($clean_text) . $video_context;

    // ── Extract images ────────────────────────────────────────────────────────
    $image_urls = array();
    preg_match_all('/<img[^>]+src=["\']([^"\']+)["\']/i', $post->post_content, $matches);
    if (!empty($matches[1])) {
        $image_urls = array_merge($image_urls, $matches[1]);
    }
    if (has_post_thumbnail($post_id)) {
        $featured = get_the_post_thumbnail_url($post_id, 'full');
        if ($featured) $image_urls[] = $featured;
    }
    $image_urls = array_values(array_unique($image_urls));


    // Send image URLs directly — the FastAPI backend fetches and analyzes them via vision model
    $payload = array(
        'lesson_id'     => (string)$post_id,
        'content'       => $clean_text,
        'image_urls'    => $image_urls
    );

    $api_url = 'https://lms-chatbot-api.vercel.app/api/ingest';
    $api_key = 'test_key_123';

    $response = wp_remote_post($api_url, array(
        'method'   => 'POST',
        'blocking' => true,
        'headers'  => array(
            'Content-Type' => 'application/json',
            'X-API-Key'    => $api_key
        ),
        'body'    => json_encode($payload),
        'timeout' => 45
    ));

    if (is_wp_error($response)) {
        error_log("Ingestion failed: " . $response->get_error_message());
    } else {
        $code = wp_remote_retrieve_response_code($response);
        $body = wp_remote_retrieve_body($response);
        error_log("Ingestion response code: " . $code);
        error_log("Ingestion response body: " . $body);

        // ── Mark this post as chatbot-enabled only on successful ingestion ──
        if ($code >= 200 && $code < 300) {
            update_post_meta($post_id, 'chatbot_enabled', '1');
            error_log("Chatbot enabled for post ID: " . $post_id);
        }
    }
}

// ht_convert_image_url_to_base64() removed — images are now sent as plain URLs


// ─────────────────────────────────────────────────────────────────────────────
// 2. UI INJECTOR: Injects the floating HTML Chat window into the footer
// ─────────────────────────────────────────────────────────────────────────────
add_action('wp_footer', 'ht_inject_chatbot_ui');
function ht_inject_chatbot_ui() {
    if (!is_single() && !is_category()) return;

    // Only show chatbot on single posts that have been ingested (chatbot_enabled = 1)
    if (is_single()) {
        global $post;
        if (!get_post_meta($post->ID, 'chatbot_enabled', true)) return;
    }

    if (is_category()) {
        $category   = get_queried_object();
        $context_id = 'category_' . $category->slug;
    } else {
        global $post;
        $context_id = (string)$post->ID;
    }
    ?>
    <script>window.WP_CHAT_CONTEXT = { lesson_id: "<?php echo esc_js($context_id); ?>" };</script>
    <div id="ht-chat-widget">
        <!-- Chat icon uses CSS background-image (immune to theme SVG resets) -->
        <button id="ht-chat-toggle" class="ht-chat-btn" aria-label="Open chat"></button>
        <div id="ht-chat-window" class="ht-chat-hidden">
            <div class="ht-chat-header">
                <h3>¡Vamos! Assistant</h3>
                <button id="ht-chat-close" aria-label="Close chat">×</button>
            </div>
            <div id="ht-chat-messages" class="ht-chat-body">
                <div class="ht-message system">Hello! I can answer questions strictly about this specific page content. Ask away!</div>
            </div>
            <div class="ht-chat-footer">
                <textarea id="ht-chat-input" placeholder="Ask me about this lesson..." autocomplete="off" rows="1"></textarea>
                <button id="ht-chat-send">Send</button>
            </div>
        </div>
    </div>
    <?php
}


// ─────────────────────────────────────────────────────────────────────────────
// 3. STYLE INJECTOR: Injects clean glassmorphism styling into the header
// ─────────────────────────────────────────────────────────────────────────────
add_action('wp_head', 'ht_inject_chatbot_styles');
function ht_inject_chatbot_styles() {
    if (!is_single() && !is_category()) return;

    // Only inject styles on posts where chatbot is enabled
    if (is_single()) {
        global $post;
        if (!get_post_meta($post->ID, 'chatbot_enabled', true)) return;
    }
    ?>
    <style>
        /* ── Widget Container ─────────────────────────────────────────────── */
        #ht-chat-widget {
            position: fixed;
            bottom: 28px;
            right: 28px;
            z-index: 999999;
            font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
        }

        /* ── Toggle Button — exact site red #CC0000 ───────────────────────── */
        .ht-chat-btn {
            width: 58px;
            height: 58px;
            background-color: #CC0000;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='26' height='26' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: center center;
            background-size: 26px 26px;
            border-radius: 50%;
            border: none;
            cursor: pointer;
            box-shadow: 0 3px 10px rgba(204, 0, 0, 0.35);
            transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
            padding: 0;
            outline: none;
            -webkit-appearance: none;
            appearance: none;
        }
        .ht-chat-btn:hover {
            transform: scale(1.07);
            background-color: #aa0000;
            box-shadow: 0 5px 16px rgba(204, 0, 0, 0.48);
        }

        /* ── Chat Window — clean white card matching site design ──────────── */
        #ht-chat-window {
            width: 355px;
            height: 490px;
            background: #ffffff;
            border: 1px solid #d9d9d9;
            border-radius: 6px;
            position: absolute;
            bottom: 76px;
            right: 0;
            display: flex;
            flex-direction: column;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12), 0 1px 4px rgba(0,0,0,0.06);
            overflow: hidden;
        }
        .ht-chat-hidden { display: none !important; }

        /* ── Header — site red #CC0000 bar ───────────────────────────────── */
        .ht-chat-header {
            background: #CC0000;
            color: #ffffff;
            padding: 12px 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .ht-chat-header h3 {
            margin: 0;
            font-size: 14px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 0.2px;
        }
        #ht-chat-close {
            background: rgba(255, 255, 255, 0.18);
            border: none;
            color: #ffffff;
            font-size: 18px;
            cursor: pointer;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            line-height: 1;
            transition: background 0.15s ease;
            padding: 0;
            flex-shrink: 0;
        }
        #ht-chat-close:hover { background: rgba(255, 255, 255, 0.32); }

        /* ── Message Body — light gray like site background ───────────────── */
        .ht-chat-body {
            flex: 1;
            padding: 14px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 9px;
            font-size: 14px;
            background: #f5f5f5;
        }
        .ht-chat-body::-webkit-scrollbar { width: 5px; }
        .ht-chat-body::-webkit-scrollbar-track { background: transparent; }
        .ht-chat-body::-webkit-scrollbar-thumb { background: #cccccc; border-radius: 10px; }
        .ht-chat-body::-webkit-scrollbar-thumb:hover { background: #aaaaaa; }

        /* ── Message Bubbles ──────────────────────────────────────────────── */
        .ht-message {
            padding: 9px 13px;
            border-radius: 4px;
            max-width: 86%;
            line-height: 1.45;
            word-wrap: break-word;
            font-size: 13.5px;
        }
        .ht-message.system {
            background: #ffffff;
            color: #555555;
            align-self: flex-start;
            border: 1px solid #e0e0e0;
            border-left: 3px solid #CC0000;
            font-style: italic;
            font-size: 13px;
        }
        .ht-message.user {
            background: #CC0000;
            color: #ffffff;
            align-self: flex-end;
            border-radius: 4px;
            box-shadow: 0 1px 4px rgba(204, 0, 0, 0.22);
        }
        .ht-message.bot {
            background: #ffffff;
            color: #333333;
            align-self: flex-start;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
        }

        /* ── Markdown Styles for Bot Responses ───────────────────────────── */
        .ht-message.bot h1,
        .ht-message.bot h2,
        .ht-message.bot h3,
        .ht-message.bot h4 { margin: 10px 0 5px 0; font-size: 14px; font-weight: 700; color: #CC0000; }
        .ht-message.bot h1:first-child,
        .ht-message.bot h2:first-child,
        .ht-message.bot h3:first-child { margin-top: 0; }
        .ht-message.bot p { margin: 0 0 7px 0; }
        .ht-message.bot p:last-child { margin-bottom: 0; }
        .ht-message.bot ul,
        .ht-message.bot ol { margin: 5px 0 9px 0; padding-left: 20px; }
        .ht-message.bot li { margin-bottom: 3px; }
        .ht-message.bot a { color: #CC0000; text-decoration: underline; }
        .ht-message.bot code {
            font-family: "Courier New", Consolas, monospace;
            background: #f2f2f2;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 12.5px;
            color: #333333;
            border: 1px solid #e0e0e0;
        }
        .ht-message.bot pre {
            background: #f5f5f5;
            padding: 8px 10px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 7px 0;
            border: 1px solid #e0e0e0;
        }
        .ht-message.bot pre code { background: none; padding: 0; border: none; font-size: 12.5px; }
        .ht-message.bot strong { font-weight: 700; color: #222222; }
        .ht-message.bot blockquote {
            border-left: 3px solid #CC0000;
            padding-left: 10px;
            margin: 7px 0;
            color: #666666;
            font-style: italic;
        }

        /* ── Footer / Input Area ──────────────────────────────────────────── */
        .ht-chat-footer {
            padding: 10px;
            display: flex;
            gap: 7px;
            background: #ffffff;
            border-top: 1px solid #e0e0e0;
            align-items: flex-end;
            flex-shrink: 0;
        }
        #ht-chat-input {
            flex: 1;
            padding: 8px 11px;
            border: 1px solid #cccccc;
            border-radius: 4px;
            font-size: 13.5px;
            font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
            outline: none;
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
            resize: none;
            height: 38px;
            min-height: 38px;
            max-height: 120px;
            box-sizing: border-box;
            overflow-y: hidden;
            line-height: 1.4;
            color: #333333;
            background: #fafafa;
        }
        #ht-chat-input::placeholder { color: #999999; }
        #ht-chat-input:focus {
            border-color: #CC0000;
            box-shadow: 0 0 0 2px rgba(204, 0, 0, 0.12);
            background: #ffffff;
        }
        #ht-chat-send {
            background: #CC0000;
            color: #ffffff;
            border: none;
            padding: 0 15px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13.5px;
            font-weight: 600;
            font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
            height: 38px;
            box-sizing: border-box;
            transition: background-color 0.15s ease, transform 0.1s ease;
            letter-spacing: 0.2px;
        }
        #ht-chat-send:hover {
            background: #aa0000;
            transform: translateY(-1px);
        }
        #ht-chat-send:active { transform: translateY(0); background: #990000; }
    </style>
    <?php
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. JAVASCRIPT ENGINE: Connects frontend chat interactions to FastAPI
// ─────────────────────────────────────────────────────────────────────────────
add_action('wp_footer', 'ht_inject_chatbot_js', 99);
function ht_inject_chatbot_js() {
    if (!is_single() && !is_category()) return;

    // Only inject JS on posts where chatbot is enabled
    if (is_single()) {
        global $post;
        if (!get_post_meta($post->ID, 'chatbot_enabled', true)) return;
    }
    ?>
    <!-- Load marked.js for Markdown rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
    document.addEventListener('DOMContentLoaded', function () {
        const toggleBtn    = document.getElementById('ht-chat-toggle');
        const closeBtn     = document.getElementById('ht-chat-close');
        const chatWindow   = document.getElementById('ht-chat-window');
        const sendBtn      = document.getElementById('ht-chat-send');
        const chatInput    = document.getElementById('ht-chat-input');
        const msgContainer = document.getElementById('ht-chat-messages');

        // Maintain conversation context across messages
        const chatHistory = [];

        toggleBtn.addEventListener('click', () => {
            chatWindow.classList.toggle('ht-chat-hidden');
            if (!chatWindow.classList.contains('ht-chat-hidden')) {
                chatInput.focus();
                autoResizeInput();
            }
        });
        closeBtn.addEventListener('click', () => chatWindow.classList.add('ht-chat-hidden'));

        // Auto-resize textarea as the user types
        function autoResizeInput() {
            chatInput.style.height = 'auto';
            const borderHeight = chatInput.offsetHeight - chatInput.clientHeight;
            let newHeight = chatInput.scrollHeight + borderHeight;
            if (newHeight < 38) newHeight = 38;
            if (newHeight > 120) {
                chatInput.style.height = '120px';
                chatInput.style.overflowY = 'auto';
            } else {
                chatInput.style.height = newHeight + 'px';
                chatInput.style.overflowY = 'hidden';
            }
        }
        chatInput.addEventListener('input', autoResizeInput);

        async function sendMessage() {
            const text = chatInput.value.trim();
            if (!text) return;

            appendMessage(text, 'user');
            chatInput.value = '';
            autoResizeInput();

            const botMessageDiv = appendMessage('...', 'bot');

            chatHistory.push({ role: 'user', content: text });

            let accumulatedResponse = '';

            try {
                const response = await fetch('https://lms-chatbot-api.vercel.app/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-API-Key': 'test_key_123'
                    },
                    body: JSON.stringify({
                        lesson_id:    window.WP_CHAT_CONTEXT.lesson_id,
                        message:      text,
                        chat_history: chatHistory.slice(0, -1)
                    })
                });

                if (!response.ok) throw new Error("Connection failed");

                const reader  = response.body.getReader();
                const decoder = new TextDecoder();
                botMessageDiv.innerHTML = ''; // Clear loading dots

                let buffer = '';
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop(); // Keep incomplete last line in buffer

                    for (const line of lines) {
                        const trimmedLine = line.trim();
                        if (!trimmedLine.startsWith('data: ')) continue;

                        let rawData = trimmedLine.slice(6);
                        if (rawData.trim() === '[DONE]') break;

                        let content = '';
                        try {
                            const parsed = JSON.parse(rawData);
                            content = parsed.token || '';
                        } catch (e) {
                            content = rawData; // Fallback for plain-text streams
                        }

                        accumulatedResponse += content;

                        if (window.marked && typeof window.marked.parse === 'function') {
                            botMessageDiv.innerHTML = window.marked.parse(accumulatedResponse);
                        } else {
                            botMessageDiv.textContent = accumulatedResponse;
                        }
                        msgContainer.scrollTop = msgContainer.scrollHeight;
                    }
                }

                chatHistory.push({ role: 'assistant', content: accumulatedResponse });

            } catch (err) {
                botMessageDiv.textContent = "Sorry, could not reach the server right now.";
            }
        }

        function appendMessage(text, sender) {
            const msg = document.createElement('div');
            msg.className = 'ht-message ' + sender;
            msg.innerText = text;
            msgContainer.appendChild(msg);
            msgContainer.scrollTop = msgContainer.scrollHeight;
            return msg;
        }

        sendBtn.addEventListener('click', sendMessage);

        // Enter = send, Shift+Enter = new line
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    });
    </script>
    <?php
}
