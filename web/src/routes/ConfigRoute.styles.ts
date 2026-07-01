import styles from "./ConfigRoute.module.css";

const safeStyles = new Proxy(styles as Record<string, string>, {
  get(target, key) {
    if (typeof key !== "string") {
      return undefined;
    }
    return target[key] ?? key;
  },
});

export default safeStyles;
