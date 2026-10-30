<?php
/**
 * Plugin Name: Moteur de recommandation
 * Description: Questionnaire de recommandation produits connecté au moteur.
 *              Utilisation : shortcode [moteur_recommandation]
 * Version:     1.3.0
 * Requires PHP: 7.4
 * License:     GPL-2.0-or-later
 */

if (!defined('ABSPATH')) {
    exit; // no direct access
}

// The version is appended to every asset URL. Bump it on any change to
// CSS or JS, otherwise browsers keep serving the cached copy.
define('RECO_VERSION', '1.3.0');

/* ==========================================================================
   Settings page  (Réglages -> Moteur de recommandation)
   ========================================================================== */

add_action('admin_menu', function () {
    add_options_page(
        'Moteur de recommandation',
        'Moteur de recommandation',
        'manage_options',
        'reco-engine',
        'reco_settings_page'
    );
});

add_action('admin_init', function () {
    register_setting('reco_settings', 'reco_api_url', [
        'type'              => 'string',
        'sanitize_callback' => 'esc_url_raw',
        'default'           => '',
    ]);
    register_setting('reco_settings', 'reco_float', [
        'type'              => 'boolean',
        'sanitize_callback' => 'rest_sanitize_boolean',
        'default'           => false,
    ]);
    register_setting('reco_settings', 'reco_enable_free_text', [
        'type'              => 'boolean',
        'sanitize_callback' => 'rest_sanitize_boolean',
        'default'           => false,
    ]);
});

function reco_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    $url    = get_option('reco_api_url', '');
    $status = '';

    if ($url) {
        $res = wp_remote_get(trailingslashit($url) . 'health', ['timeout' => 8]);
        if (is_wp_error($res)) {
            $status = '<span style="color:#a63d57">Injoignable : '
                . esc_html($res->get_error_message()) . '</span>';
        } else {
            $body = json_decode(wp_remote_retrieve_body($res), true);
            if (!empty($body['products'])) {
                $status = '<span style="color:#2e6b4f">Connecté — '
                    . intval($body['products']) . ' produits, '
                    . intval($body['packs']) . ' packs</span>';
            } else {
                $status = '<span style="color:#a63d57">Réponse inattendue</span>';
            }
        }
    }
    ?>
    <div class="wrap">
        <h1>Moteur de recommandation</h1>
        <form method="post" action="options.php">
            <?php settings_fields('reco_settings'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="reco_api_url">URL de l'API</label></th>
                    <td>
                        <input name="reco_api_url" id="reco_api_url" type="url"
                               class="regular-text" value="<?php echo esc_attr($url); ?>"
                               placeholder="https://exemple.com/api/reco">
                        <p class="description">
                            Sans barre oblique finale. Le serveur WordPress doit
                            pouvoir joindre cette adresse.
                        </p>
                    </td>
                </tr>
                <tr>
                    <th scope="row">Recherche en langage naturel</th>
                    <td>
                        <label>
                            <input type="checkbox" name="reco_enable_free_text" value="1"
                                <?php checked(get_option('reco_enable_free_text')); ?>>
                            Autoriser le client à décrire son besoin en une phrase
                        </label>
                        <p class="description">
                            Nécessite que <code>ENABLE_INTERPRET</code> soit activé
                            côté API.
                        </p>
                    </td>
                </tr>
                <tr>
                    <th scope="row">Conseiller flottant</th>
                    <td>
                        <label>
                            <input type="checkbox" name="reco_float" value="1"
                                <?php checked(get_option('reco_float')); ?>>
                            Afficher une bulle de conseil sur toutes les pages
                        </label>
                        <p class="description">
                            Recommandé : le client obtient un conseil pendant
                            qu’il regarde les produits, sans quitter sa page.
                            La conversation le suit d’une page à l’autre.
                            Nécessite l’option ci-dessus.
                        </p>
                    </td>
                </tr>
                <tr>
                    <th scope="row">État</th>
                    <td><?php echo $status ?: '<em>Renseignez l’URL de l’API.</em>'; ?></td>
                </tr>
                <tr>
                    <th scope="row">Utilisation</th>
                    <td>
                        <code>[moteur_recommandation]</code> — questionnaire
                        guidé.<br>
                        <code>[conseiller_beaute]</code> — conseiller
                        conversationnel sur une page dédiée.<br>
                        Pour une bulle sur tout le site, aucun code court
                        n’est nécessaire : cochez l’option ci-dessous.
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}

/* ==========================================================================
   Server-side proxy

   The browser never calls the recommendation API directly. Going through
   WordPress means: no CORS configuration, the API host stays private, and
   requests can be rate-limited or logged in one place later.
   ========================================================================== */

add_action('rest_api_init', function () {
    foreach (['recommend', 'options', 'interpret', 'chat'] as $route) {
        register_rest_route('reco/v1', '/' . $route, [
            'methods'             => $route === 'options' ? 'GET' : 'POST',
            'callback'            => 'reco_proxy',
            'permission_callback' => '__return_true', // public storefront widget
        ]);
    }
});

function reco_proxy(WP_REST_Request $request) {
    $api = get_option('reco_api_url', '');
    if (!$api) {
        return new WP_Error('reco_not_configured',
            "L'URL de l'API n'est pas configurée.", ['status' => 503]);
    }

    $route = basename($request->get_route());

    if (in_array($route, ['interpret', 'chat'], true)
        && !get_option('reco_enable_free_text')) {
        return new WP_Error('reco_disabled',
            'Fonction désactivée.', ['status' => 403]);
    }

    $target = trailingslashit($api) . $route;
    $args   = ['timeout' => 120, 'headers' => ['content-type' => 'application/json']];

    if ($request->get_method() === 'GET') {
        $domain = sanitize_key($request->get_param('domain') ?: 'visage');
        $target = add_query_arg('domain', $domain, $target);
        $res    = wp_remote_get($target, $args);
    } else {
        $args['body'] = wp_json_encode($request->get_json_params());
        $res          = wp_remote_post($target, $args);
    }

    if (is_wp_error($res)) {
        return new WP_Error('reco_unreachable',
            'Service indisponible.', ['status' => 502]);
    }

    $code = wp_remote_retrieve_response_code($res);
    $body = json_decode(wp_remote_retrieve_body($res), true);

    if ($code >= 400) {
        $detail = is_array($body) && isset($body['detail'])
            ? $body['detail'] : 'Erreur du service.';
        return new WP_Error('reco_error', $detail, ['status' => $code]);
    }
    return rest_ensure_response($body);
}

/* ==========================================================================
   Shortcode
   ========================================================================== */

/**
 * Floating adviser, injected into every page when enabled.
 *
 * A conversation is far more useful beside the products than on a page of its
 * own, so this is the mode a shop normally wants; the shortcode remains for a
 * dedicated advice page.
 */
add_action('wp_footer', function () {
    if (!get_option('reco_float') || !get_option('reco_api_url')
        || !get_option('reco_enable_free_text')) {
        return;
    }
    // avoid two chats on the same page when the shortcode is also present
    global $post;
    if ($post instanceof WP_Post
        && has_shortcode($post->post_content, 'conseiller_beaute')) {
        return;
    }

    wp_enqueue_style('reco-engine',
        plugins_url('assets/reco.css', __FILE__), [], RECO_VERSION);
    wp_enqueue_script('reco-chat',
        plugins_url('assets/chat.js', __FILE__), [], RECO_VERSION, true);
    wp_localize_script('reco-chat', 'RECO_CFG', [
        'root'  => esc_url_raw(rest_url('reco/v1/')),
        'nonce' => wp_create_nonce('wp_rest'),
        'shop'  => trailingslashit(home_url('/')),
    ]);

    echo '<div id="reco-chat-float" class="reco-app reco-float"></div>';
});

add_shortcode('conseiller_beaute', function () {
    if (!get_option('reco_api_url')) {
        return current_user_can('manage_options')
            ? '<p><em>Conseiller : URL de l’API non configurée.</em></p>' : '';
    }
    if (!get_option('reco_enable_free_text')) {
        return current_user_can('manage_options')
            ? '<p><em>Conseiller : activez « recherche en langage naturel » '
              . 'dans les réglages.</em></p>' : '';
    }

    wp_enqueue_style('reco-engine',
        plugins_url('assets/reco.css', __FILE__), [], RECO_VERSION);
    wp_enqueue_script('reco-chat',
        plugins_url('assets/chat.js', __FILE__), [], RECO_VERSION, true);

    wp_localize_script('reco-chat', 'RECO_CFG', [
        'root'  => esc_url_raw(rest_url('reco/v1/')),
        'nonce' => wp_create_nonce('wp_rest'),
        'shop'  => trailingslashit(home_url('/')),
    ]);

    return '<div id="reco-chat" class="reco-app reco-chat"></div>';
});

add_shortcode('moteur_recommandation', function () {
    if (!get_option('reco_api_url')) {
        return current_user_can('manage_options')
            ? '<p><em>Moteur de recommandation : URL de l’API non configurée '
              . '(Réglages → Moteur de recommandation).</em></p>'
            : '';
    }

    wp_enqueue_style('reco-engine',
        plugins_url('assets/reco.css', __FILE__), [], RECO_VERSION);
    wp_enqueue_script('reco-engine',
        plugins_url('assets/reco.js', __FILE__), [], RECO_VERSION, true);

    wp_localize_script('reco-engine', 'RECO_CFG', [
        'root'     => esc_url_raw(rest_url('reco/v1/')),
        'nonce'    => wp_create_nonce('wp_rest'),
        'freeText' => (bool) get_option('reco_enable_free_text'),
        // WooCommerce accepts ?add-to-cart=ID on any page, so the basket
        // works as a plain link with no extra JavaScript.
        'shop'     => trailingslashit(home_url('/')),
    ]);

    return '<div id="reco-app" class="reco-app">'
         . '<p class="reco-loading">Chargement…</p></div>';
});
