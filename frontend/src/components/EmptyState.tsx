interface EmptyStateProps {
  title: string;
  subtitle: string;
  icon?: 'contour' | 'upload' | 'run';
}

export default function EmptyState({ title, subtitle, icon = 'contour' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6" style={{ color: 'var(--ink-muted)' }}>
      <svg width="160" height="120" viewBox="0 0 160 120" aria-hidden>
        {icon === 'contour' && [0, 1, 2, 3, 4, 5].map((i) => (
          <path
            key={i}
            d={`M ${10 + i * 4} ${100 - i * 12} Q ${50 + i * 3} ${70 - i * 14} ${80 + i * 2} ${80 - i * 10} T ${150 - i * 4} ${60 - i * 8}`}
            stroke="var(--slate-200)"
            strokeWidth="1"
            fill="none"
            opacity={0.5 + i * 0.08}
          />
        ))}
        {icon === 'upload' && (
          <>
            <rect x="40" y="35" width="80" height="60" rx="4" stroke="var(--slate-200)" strokeWidth="1.5" fill="none" />
            <path d="M70 50v30M70 50l-12 12M70 50l12 12" stroke="var(--teal-700)" strokeWidth="1.75" fill="none" strokeLinecap="round" />
          </>
        )}
        {icon === 'run' && (
          <>
            <circle cx="80" cy="60" r="30" stroke="var(--slate-200)" strokeWidth="1.5" fill="none" />
            <path d="M70 48l20 12-20 12z" fill="var(--teal-700)" />
          </>
        )}
      </svg>
      <div className="text-center">
        <p className="font-display font-700 text-lg" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>
          {title}
        </p>
        <p className="mt-1 text-sm" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem' }}>
          {subtitle}
        </p>
      </div>
    </div>
  );
}
