# Composer Button States Design

## Goal

Make the Chat/Coding composer action buttons feel closer to Codex: quiet by default, clearly responsive on hover/focus/active, and visually distinct for send, stop, and disabled states.

## Scope

- Update only the ConversationView composer button style slices.
- Cover the image attach button, enabled send button, stop/running button, and disabled behavior.
- Keep the current compact square geometry and existing VUI/HeroUI primitives.
- Do not redesign the conversation timeline, process trace, route shell, or global button system.

## Design

Default icon buttons use a transparent/subtle mixed surface with a soft border and tertiary/secondary foreground. Hover and focus raise contrast with a muted row background, stronger border, and primary foreground. Active/pressed uses a slightly deeper surface, no translation, and no layout shift.

The primary send button uses a cooler accent mix with a clearer border and hover/focus lift, but stays calm rather than becoming a saturated CTA. The stop button uses a warm/error mix so it is distinguishable from normal send without feeling alarming. Disabled buttons keep stable geometry, reduce opacity, and suppress strong hover emphasis.

## Validation

- `npm --prefix web run test -- ConversationView.test.tsx ChatCodingRoute.layout.test.ts`
- `npm --prefix web run build`
- Visual review of the Chat/Coding composer at desktop width when the local runtime/browser is available.
