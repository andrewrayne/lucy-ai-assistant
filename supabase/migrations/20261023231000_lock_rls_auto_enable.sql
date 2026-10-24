-- Supabase's "automatic RLS" helper is a SECURITY DEFINER function that the public
-- API roles could call. It only needs to run from its event trigger, so close it.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
