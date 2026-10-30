-- export.sql  v2
-- FIX: v1 had  AND p.post_content <> ''  which silently dropped packs
-- (pack pages often have no body copy). Now we keep a product if it has
-- EITHER a description OR a short description OR is clearly a pack.
--
-- Run:
--   sudo mysql letsbebi --batch --raw --skip-column-names < export.sql > products.jsonl

SELECT JSON_OBJECT(
  'id',            p.ID,
  'name',          p.post_title,
  'slug',          p.post_name,
  'short_desc',    p.post_excerpt,
  'description',   LEFT(p.post_content, 4000),
  'price',         (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = '_price' LIMIT 1),
  'regular_price', (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = '_regular_price' LIMIT 1),
  'stock',         (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = '_stock' LIMIT 1),
  'stock_status',  (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = '_stock_status' LIMIT 1),
  'total_sales',   (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = 'total_sales' LIMIT 1),
  'rating',        (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = '_wc_average_rating' LIMIT 1),
  'image_id',      (SELECT meta_value FROM wp_11e347_postmeta
                     WHERE post_id = p.ID AND meta_key = '_thumbnail_id' LIMIT 1),
  'brand',         (SELECT GROUP_CONCAT(t.name SEPARATOR ', ')
                      FROM wp_11e347_term_relationships tr
                      JOIN wp_11e347_term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
                      JOIN wp_11e347_terms t ON t.term_id = tt.term_id
                     WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_brand'),
  'categories',    (SELECT GROUP_CONCAT(t.name SEPARATOR ', ')
                      FROM wp_11e347_term_relationships tr
                      JOIN wp_11e347_term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
                      JOIN wp_11e347_terms t ON t.term_id = tt.term_id
                     WHERE tr.object_id = p.ID
                       AND tt.taxonomy = 'product_cat'
                       AND t.slug NOT IN ('accueil','promos','destockage','racine','uncategorized')),
  'categories_all',(SELECT GROUP_CONCAT(t.name SEPARATOR ', ')
                      FROM wp_11e347_term_relationships tr
                      JOIN wp_11e347_term_taxonomy tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
                      JOIN wp_11e347_terms t ON t.term_id = tt.term_id
                     WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_cat')
) AS j
FROM wp_11e347_posts p
WHERE p.post_type = 'product'
  AND p.post_status = 'publish'
  AND (
        p.post_content <> ''
     OR p.post_excerpt <> ''
     OR p.post_title REGEXP '(^| )(Pack|Duo|Trio|Coffret|Routine|Kit|Set|Lot)'
  )
ORDER BY p.ID;
