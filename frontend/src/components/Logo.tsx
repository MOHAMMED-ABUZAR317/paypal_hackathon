export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="RainCheck"
      className="logo"
    >
      <rect width="64" height="64" rx="16" fill="var(--ink)" />
      <path
        d="M32 10c8.4 8.9 15 17.4 15 24.6A15 15 0 0 1 17 34.6C17 27.4 23.6 18.9 32 10Z"
        fill="var(--rain)"
      />
      <path
        d="M25 36.5l6 6 12-13"
        fill="none"
        stroke="var(--ink)"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
