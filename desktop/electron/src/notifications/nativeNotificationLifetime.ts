type NativeNotification = {
  once(event: "click" | "failed", listener: () => void): unknown;
};

/** Keep native delegates alive, including notifications hidden in Action Center. */
export class NativeNotificationLifetime {
  private readonly live = new Set<NativeNotification>();
  constructor(private readonly capacity = 200) {}

  retain(notification: NativeNotification): void {
    this.live.add(notification);
    while (this.live.size > Math.max(1, this.capacity)) this.live.delete(this.live.values().next().value!);
    const release = () => { this.live.delete(notification); };
    notification.once("click", release);
    notification.once("failed", release);
    // Windows reports close for popup timeout while Action Center can still
    // activate it. Capacity bounds those references without dropping clicks.
  }

  get size(): number { return this.live.size; }
}
