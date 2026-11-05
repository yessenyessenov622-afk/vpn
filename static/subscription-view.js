// Pure presentation: subscription source and last confirmed VPN state are independent.
function subscriptionPresentation(account, labels, notes, now, unknownVpnTitle) {
  const sub = account.subscription;
  const state = !sub ? labels.none : sub.expires_at > now ? labels.active : labels.expired;
  const source = sub ? labels[account.source] : '';
  const explanation = sub ? notes[account.source + 'Explanation'] : '';
  const vpnText = account.vpn === 'none' ? labels.vpnNone : account.vpn === 'allowed' ? labels.vpnAllowed : account.vpn === 'revoked' ? labels.vpnRevoked : labels.vpnUnknown;
  const vpnTitle = account.vpn === 'none' ? labels.vpnNoneTitle : account.vpn === 'allowed' ? labels.vpnAllowedTitle : account.vpn === 'revoked' ? labels.vpnRevokedTitle : unknownVpnTitle;
  return {state, source, explanation, vpnText, vpnTitle};
}
