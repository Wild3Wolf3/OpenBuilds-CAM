class PID:
    """PID with output clamped to 0..1, integral anti-windup and
    derivative on measurement (no kick when the setpoint jumps)."""

    def __init__(self, kp, ki, kd):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.reset()

    def reset(self):
        self.integral = 0.0
        self.last_input = None

    def update(self, setpoint, measured, dt):
        error = setpoint - measured
        deriv = 0.0
        if self.last_input is not None and dt > 0:
            deriv = -(measured - self.last_input) / dt
        self.last_input = measured
        p = self.kp * error
        d = self.kd * deriv
        candidate = self.integral + self.ki * error * dt
        out = p + candidate + d
        # Only integrate when it doesn't push further into saturation.
        if (out < 1.0 or error < 0) and (out > 0.0 or error > 0):
            self.integral = min(1.0, max(-1.0, candidate))
        return min(1.0, max(0.0, p + self.integral + d))
