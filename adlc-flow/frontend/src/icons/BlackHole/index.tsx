import React from "react";

export const BlackHoleIcon = React.forwardRef<
  SVGSVGElement,
  React.SVGProps<SVGSVGElement>
>(({ className = "h-5 w-5", ...props }, ref) => (
  <svg
    ref={ref}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    {...props}
  >
    {/* Outer Accretion Disk / Spirals */}
    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" strokeOpacity="0.25" />
    <path d="M12 4a8 8 0 0 1 7.4 5" strokeOpacity="0.5" />
    <path d="M12 20a8 8 0 0 1-7.4-5" strokeOpacity="0.5" />
    <path d="M4.6 9A8 8 0 0 1 9.6 4.6" />
    <path d="M19.4 15a8 8 0 0 1-5 4.4" />
    {/* Event Horizon (Black Hole Center) */}
    <circle cx="12" cy="12" r="4.5" fill="currentColor" />
  </svg>
));

BlackHoleIcon.displayName = "BlackHoleIcon";
export default BlackHoleIcon;
