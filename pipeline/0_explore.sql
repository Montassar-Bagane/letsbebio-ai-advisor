-- ============================================================
-- WooCommerce product data exploration
-- DB prefix: wp_11e347_
-- Run:  sudo mysql letsbebi < explore.sql > report.txt
-- ============================================================

SELECT '===== 0. POST TYPES (how many products?) =====' AS '';
SELECT post_type, post_status, COUNT(*) AS n
FROM wp_11e347_posts
GROUP BY post_type, post_status
HAVING n > 5
ORDER BY n DESC;

SELECT '===== 0b. PRODUCT TYPES (simple/variable/grouped/bundle) =====' AS '';
SELECT t.name AS product_type, tt.count AS n
FROM wp_11e347_terms t
JOIN wp_11e347_term_taxonomy tt ON t.term_id = tt.term_id
WHERE tt.taxonomy = 'product_type'
ORDER BY tt.count DESC;

SELECT '===== 1. PRODUCT CATEGORIES (with hierarchy) =====' AS '';
SELECT tt.term_id,
       tt.parent,
       parent.name AS parent_name,
       t.name      AS category,
       t.slug,
       tt.count    AS products
FROM wp_11e347_term_taxonomy tt
JOIN wp_11e347_terms t       ON t.term_id = tt.term_id
LEFT JOIN wp_11e347_terms parent ON parent.term_id = tt.parent
WHERE tt.taxonomy = 'product_cat'
ORDER BY tt.parent, tt.count DESC;

SELECT '===== 2. WHAT FIELDS DOES A PRODUCT HAVE (meta keys) =====' AS '';
SELECT pm.meta_key, COUNT(*) AS used_on_n_products
FROM wp_11e347_postmeta pm
JOIN wp_11e347_posts p ON p.ID = pm.post_id
WHERE p.post_type = 'product'
GROUP BY pm.meta_key
ORDER BY used_on_n_products DESC
LIMIT 80;

SELECT '===== 3. GLOBAL ATTRIBUTES (registered) =====' AS '';
SELECT attribute_id, attribute_name, attribute_label, attribute_type
FROM wp_11e347_woocommerce_attribute_taxonomies;

SELECT '===== 3b. ATTRIBUTE VALUES IN USE =====' AS '';
SELECT tt.taxonomy, t.name AS value, tt.count AS products
FROM wp_11e347_term_taxonomy tt
JOIN wp_11e347_terms t ON t.term_id = tt.term_id
WHERE tt.taxonomy LIKE 'pa_%'
ORDER BY tt.taxonomy, tt.count DESC;

SELECT '===== 4. PRODUCT TAGS =====' AS '';
SELECT t.name AS tag, t.slug, tt.count AS products
FROM wp_11e347_term_taxonomy tt
JOIN wp_11e347_terms t ON t.term_id = tt.term_id
WHERE tt.taxonomy = 'product_tag'
ORDER BY tt.count DESC;

SELECT '===== 4b. ALL OTHER TAXONOMIES (brands? custom?) =====' AS '';
SELECT taxonomy, COUNT(*) AS n_terms, SUM(count) AS n_assignments
FROM wp_11e347_term_taxonomy
GROUP BY taxonomy
ORDER BY n_terms DESC;

SELECT '===== 5. SKIN / HAIR TYPE SIGNALS =====' AS '';
SELECT tt.taxonomy, t.name, tt.count
FROM wp_11e347_term_taxonomy tt
JOIN wp_11e347_terms t ON t.term_id = tt.term_id
WHERE t.name REGEXP 'peau|cheveu|skin|hair|sec|gras|sensib|mixte|dry|oily|sensitive|normal|frisé|bouclé|crép|curl|age|rid|acn|tach'
ORDER BY tt.taxonomy, tt.count DESC;

SELECT '===== 6. PACKS / ROUTINES / BUNDLES =====' AS '';
SELECT ID, post_title, post_type, post_status
FROM wp_11e347_posts
WHERE post_type IN ('product','product_variation')
  AND post_status = 'publish'
  AND post_title REGEXP 'pack|routine|coffret|kit|bundle|duo|trio|set|lot'
LIMIT 60;

SELECT '===== 7. SAMPLE: 10 REAL PRODUCTS, FULL RECORD =====' AS '';
SELECT p.ID,
       p.post_title,
       LEFT(p.post_excerpt, 300)                     AS short_description,
       LEFT(p.post_content, 600)                     AS description,
       (SELECT GROUP_CONCAT(t.name SEPARATOR ' | ')
          FROM wp_11e347_term_relationships tr
          JOIN wp_11e347_term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
          JOIN wp_11e347_terms t ON t.term_id = tt.term_id
         WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_cat')  AS categories,
       (SELECT GROUP_CONCAT(t.name SEPARATOR ' | ')
          FROM wp_11e347_term_relationships tr
          JOIN wp_11e347_term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
          JOIN wp_11e347_terms t ON t.term_id = tt.term_id
         WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_tag')  AS tags,
       (SELECT GROUP_CONCAT(CONCAT(tt.taxonomy, '=', t.name) SEPARATOR ' | ')
          FROM wp_11e347_term_relationships tr
          JOIN wp_11e347_term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
          JOIN wp_11e347_terms t ON t.term_id = tt.term_id
         WHERE tr.object_id = p.ID AND tt.taxonomy LIKE 'pa_%')      AS attributes,
       (SELECT meta_value FROM wp_11e347_postmeta
         WHERE post_id = p.ID AND meta_key = '_price'  LIMIT 1)      AS price,
       (SELECT meta_value FROM wp_11e347_postmeta
         WHERE post_id = p.ID AND meta_key = '_sku'    LIMIT 1)      AS sku,
       (SELECT meta_value FROM wp_11e347_postmeta
         WHERE post_id = p.ID AND meta_key = '_stock'  LIMIT 1)      AS stock,
       (SELECT meta_value FROM wp_11e347_postmeta
         WHERE post_id = p.ID AND meta_key = '_product_attributes' LIMIT 1) AS local_attributes
FROM wp_11e347_posts p
WHERE p.post_type = 'product' AND p.post_status = 'publish'
ORDER BY RAND()
LIMIT 10\G

SELECT '===== 8. DESCRIPTION COMPLETENESS (is the data usable?) =====' AS '';
SELECT COUNT(*)                                                        AS published_products,
       SUM(post_content = '')                                          AS empty_description,
       SUM(post_excerpt = '')                                          AS empty_short_desc,
       ROUND(AVG(CHAR_LENGTH(post_content)))                           AS avg_desc_chars
FROM wp_11e347_posts
WHERE post_type = 'product' AND post_status = 'publish';
