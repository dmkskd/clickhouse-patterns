-- Pattern-local source write timestamps, populated before the snapshot.
CREATE FUNCTION public.touch_order_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;
ALTER TABLE public.orders
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();
CREATE TRIGGER orders_updated_at BEFORE UPDATE ON public.orders
FOR EACH ROW EXECUTE FUNCTION public.touch_order_updated_at();
TRUNCATE public.orders;
INSERT INTO public.orders (id, customer, amount) VALUES
    (1, 'alice', 100), (2, 'bob', 200), (3, 'carol', 300);
