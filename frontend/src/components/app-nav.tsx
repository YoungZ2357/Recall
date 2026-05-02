import { NavLink, useLocation } from 'react-router-dom';
import styles from './app-nav.module.css';

const NAV_ITEMS = [
  { label: 'Search', to: '/search' },
  { label: 'Library', to: '/library' },
  { label: 'Pipeline', to: '/pipeline' },
  { label: 'Eval', to: '/eval' },
] as const;

export function AppNav() {
  const { pathname } = useLocation();

  return (
    <header className={styles.nav}>
      <div className={styles.left}>
        <span className={styles.logo}>Recall</span>
        <nav className={styles.links}>
          {NAV_ITEMS.map(({ label, to }) => (
            <NavLink
              key={to}
              to={to}
              className={pathname.startsWith(to) ? `${styles.link} ${styles.linkActive}` : styles.link}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
      <button className={styles.agentBtn}>Agent</button>
    </header>
  );
}
