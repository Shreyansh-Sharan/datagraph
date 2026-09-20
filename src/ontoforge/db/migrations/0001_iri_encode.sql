-- Percent-encode everything outside the RFC 3987 iunreserved set (R2RML §7.3 "IRI-safe version").
CREATE OR REPLACE FUNCTION ontoforge_iri_encode(input text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    result text := '';
    ch text;
    b bytea;
    i int;
BEGIN
    FOREACH ch IN ARRAY regexp_split_to_array(input, '') LOOP
        IF ch ~ '^[A-Za-z0-9._~-]$' THEN
            result := result || ch;
        ELSE
            b := convert_to(ch, 'UTF8');
            FOR i IN 0 .. length(b) - 1 LOOP
                result := result || '%' || lpad(upper(to_hex(get_byte(b, i))), 2, '0');
            END LOOP;
        END IF;
    END LOOP;
    RETURN result;
END
$$;
