/**
 * Engineering-line icon set — 1.75px stroke, 24px grid.
 */

import type { SVGProps } from 'react';

interface IconProps extends SVGProps<SVGSVGElement> {
  size?: number;
}

function base({ size = 18, ...props }: IconProps): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.75,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
    ...props,
  } as SVGProps<SVGSVGElement>;
}

export const IconPlus = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const IconUpload = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 5v14M5 12l7-7 7 7" />
  </svg>
);

export const IconWind = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M3 8h11a3 3 0 1 0-3-3M3 12h17a3 3 0 1 1-3 3M3 16h9a3 3 0 1 0-3 3" />
  </svg>
);

export const IconSun = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
  </svg>
);

export const IconPlay = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M8 5v14l11-7z" fill="currentColor" />
  </svg>
);

export const IconDownload = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 3v14M5 12l7 7 7-7M5 21h14" />
  </svg>
);
