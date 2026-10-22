// Who sees what in the 3D view (tested): the client's view opens with the rooms first; the
// technical line about the section's levels is for staff only.
export const roomsFirstByDefault = (portal: boolean | undefined): boolean => !!portal;
export const showsSectionLine = (portal: boolean | undefined, compact: boolean | undefined): boolean => !portal && !compact;
