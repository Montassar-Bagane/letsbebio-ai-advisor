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

function reco_get_store_products() {
    global $wpdb;
    $p = $wpdb->prefix;
    $sql = "
    SELECT p.ID AS id,
           p.post_title AS name,
           p.post_name AS slug,
           p.post_excerpt AS short_desc,
           LEFT(p.post_content, 4000) AS description,
           pm_price.meta_value AS price,
           pm_reg.meta_value AS regular_price,
           pm_stock.meta_value AS stock,
           pm_status.meta_value AS stock_status,
           pm_sales.meta_value AS total_sales,
           pm_rating.meta_value AS rating,
           pm_thumb.meta_value AS image_id,
           (SELECT GROUP_CONCAT(t.name SEPARATOR ', ')
              FROM {$p}term_relationships tr
              JOIN {$p}term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
              JOIN {$p}terms t ON t.term_id = tt.term_id
             WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_cat') AS categories
      FROM {$p}posts p
      LEFT JOIN {$p}postmeta pm_price ON pm_price.post_id = p.ID AND pm_price.meta_key = '_price'
      LEFT JOIN {$p}postmeta pm_reg ON pm_reg.post_id = p.ID AND pm_reg.meta_key = '_regular_price'
      LEFT JOIN {$p}postmeta pm_stock ON pm_stock.post_id = p.ID AND pm_stock.meta_key = '_stock'
      LEFT JOIN {$p}postmeta pm_status ON pm_status.post_id = p.ID AND pm_status.meta_key = '_stock_status'
      LEFT JOIN {$p}postmeta pm_sales ON pm_sales.post_id = p.ID AND pm_sales.meta_key = 'total_sales'
      LEFT JOIN {$p}postmeta pm_rating ON pm_rating.post_id = p.ID AND pm_rating.meta_key = '_wc_average_rating'
      LEFT JOIN {$p}postmeta pm_thumb ON pm_thumb.post_id = p.ID AND pm_thumb.meta_key = '_thumbnail_id'
     WHERE p.post_type = 'product'
       AND p.post_status = 'publish'
     ORDER BY p.ID ASC
    ";
    $rows = $wpdb->get_results($sql, ARRAY_A);
    if (!is_array($rows)) {
        return [];
    }
    foreach ($rows as &$r) {
        if (!empty($r['image_id'])) {
            $r['image_url'] = wp_get_attachment_image_url($r['image_id'], 'full');
        }
        $r['url'] = get_permalink($r['id']);
    }
    return $rows;
}

function reco_sync_catalogue_with_api() {
    $url = get_option('reco_api_url', '');
    if (!$url) {
        return ['error' => 'URL de l\'API non renseignée'];
    }
    $products = reco_get_store_products();
    if (empty($products)) {
        return ['error' => 'Aucun produit publié trouvé dans WooCommerce'];
    }
    $body = [
        'products' => $products,
        'site_url' => get_site_url(),
    ];
    $response = wp_remote_post(trailingslashit($url) . 'sync', [
        'headers' => ['Content-Type' => 'application/json'],
        'body'    => wp_json_encode($body),
        'timeout' => 45,
    ]);
    if (is_wp_error($response)) {
        return ['error' => $response->get_error_message()];
    }
    $data = json_decode(wp_remote_retrieve_body($response), true);
    return $data ?: ['status' => 'ok', 'synced' => count($products)];
}

function reco_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    $url    = get_option('reco_api_url', '');
    $status = '';
    $sync_notice = '';

    if (isset($_POST['reco_sync_now']) && check_admin_referer('reco_sync_action')) {
        $res = reco_sync_catalogue_with_api();
        if (!empty($res['error'])) {
            $sync_notice = '<div class="notice notice-error is-dismissible"><p><strong>Erreur de synchronisation :</strong> ' . esc_html($res['error']) . '</p></div>';
        } else {
            $count = isset($res['synced']) ? intval($res['synced']) : 0;
            $sync_notice = '<div class="notice notice-success is-dismissible"><p><strong>Succès :</strong> ' . $count . ' produits synchronisés directement avec l\'IA !</p></div>';
        }
    }

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
                $status = '<span style="color:#a63d57">Prêt — En attente de synchronisation</span>';
            }
        }
    }
    ?>
    <div class="wrap">
        <h1>Moteur de recommandation</h1>
        <?php echo $sync_notice; ?>
        <form method="post" action="options.php">
            <?php settings_fields('reco_settings'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="reco_api_url">URL de l'API (Render)</label></th>
                    <td>
                        <input name="reco_api_url" id="reco_api_url" type="url"
                               class="regular-text" value="<?php echo esc_attr($url); ?>"
                               placeholder="https://letsbebio-ai-advisor.onrender.com">
                        <p class="description">
                            Sans barre oblique finale. Exemple : <code>https://letsbebio-ai-advisor.onrender.com</code>
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
                        </p>
                    </td>
                </tr>
                <tr>
                    <th scope="row">État</th>
                    <td><?php echo $status ?: '<em>Renseignez l’URL de l’API.</em>'; ?></td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>

        <hr style="margin: 30px 0;">

        <h2>Synchronisation Automatique en 1 Clic (Sans identifiants SQL)</h2>
        <p class="description">
            Plus besoin de configurer de mot de passe de base de données ou d'ouvrir le port 3306 !<br>
            Cliquez sur ce bouton : WordPress extrait tous vos produits et les envoie directement à votre API Render en HTTPS sécurisé.
        </p>

        <form method="post" action="" style="margin-top: 15px;">
            <?php wp_nonce_field('reco_sync_action'); ?>
            <input type="hidden" name="reco_sync_now" value="1">
            <button type="submit" class="button button-primary button-hero" <?php disabled(empty($url)); ?>>
                ⚡ Synchroniser le catalogue avec l'IA maintenant
            </button>
        </form>

        <hr style="margin: 30px 0;">

        <h2>Configuration Automatique de la Base de Données</h2>
        <p class="description">
            Le plugin a automatiquement détecté les identifiants de la base de données WordPress.
            Copiez ce bloc directement dans votre fichier <code>service/.env</code> pour connecter le moteur Python en un clic :
        </p>

        <?php
        global $wpdb;
        $db_host_parts = explode(':', DB_HOST);
        $db_host = $db_host_parts[0];
        $db_port = isset($db_host_parts[1]) ? $db_host_parts[1] : '3306';
        if ($db_host === 'localhost') {
            $db_host = '127.0.0.1';
        }
        $env_snippet = "DB_HOST=" . esc_attr($db_host) . "\n"
                     . "DB_PORT=" . esc_attr($db_port) . "\n"
                     . "DB_USER=" . esc_attr(DB_USER) . "\n"
                     . "DB_PASSWORD=" . esc_attr(DB_PASSWORD) . "\n"
                     . "DB_NAME=" . esc_attr(DB_NAME) . "\n"
                     . "WP_PREFIX=" . esc_attr($wpdb->prefix) . "\n"
                     . "SITE_URL=" . esc_attr(get_site_url());
        ?>

        <div style="position: relative; max-width: 600px; margin-top: 15px;">
            <textarea id="reco-env-box" readonly rows="8" style="width: 100%; font-family: monospace; background: #f0f0f1; padding: 10px;"><?php echo esc_textarea($env_snippet); ?></textarea>
            <button type="button" class="button button-secondary" onclick="navigator.clipboard.writeText(document.getElementById('reco-env-box').value); alert('Copié dans le presse-papiers !');" style="margin-top: 8px;">
                📋 Copier la configuration .env
            </button>
        </div>
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
