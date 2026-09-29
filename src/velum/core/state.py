from enum import StrEnum


class State(StrEnum):
    DISCONNECTED = 'DISCONNECTED'
    VALIDATING = 'VALIDATING'
    PREPARING_NETWORK = 'PREPARING_NETWORK'
    STARTING_CORE = 'STARTING_CORE'
    WAITING_FOR_TUN = 'WAITING_FOR_TUN'
    CONFIGURING_ROUTES = 'CONFIGURING_ROUTES'
    CONFIGURING_DNS = 'CONFIGURING_DNS'
    VERIFYING = 'VERIFYING'
    CONNECTED = 'CONNECTED'
    RECONNECTING = 'RECONNECTING'
    ERROR = 'ERROR'
    CLEANUP = 'CLEANUP'
    STOPPING = 'STOPPING'
    RESTORING_NETWORK = 'RESTORING_NETWORK'


STEPS = (State.VALIDATING, State.PREPARING_NETWORK, State.STARTING_CORE,
         State.WAITING_FOR_TUN, State.CONFIGURING_ROUTES, State.CONFIGURING_DNS,
         State.VERIFYING)


class StateMachine:
    def __init__(self, notify=lambda state: None):
        self.state = State.DISCONNECTED
        self.notify = notify
        self.error = ''

    def set(self, state):
        self.state = state
        self.notify(state)

    def connect(self, actions, cleanup):
        if self.state not in (State.DISCONNECTED, State.RECONNECTING):
            raise RuntimeError('Disconnect the current session before connecting')
        self.error = ''
        try:
            for state in STEPS:
                self.set(state)
                result = actions[state]()
                if state == State.VERIFYING and result is not True:
                    raise RuntimeError('Routing verification failed; the VPN is not active')
            self.set(State.CONNECTED)
        except Exception as exc:
            self.error = str(exc)
            self.set(State.ERROR)
            self.set(State.CLEANUP)
            try:
                cleanup()
            except Exception as cleanup_error:
                self.error += '; ' + str(cleanup_error)
                self.set(State.ERROR)
            else:
                self.set(State.DISCONNECTED)
            raise

    def disconnect(self, cleanup):
        self.set(State.STOPPING)
        self.set(State.RESTORING_NETWORK)
        try:
            cleanup()
        except Exception:
            self.set(State.ERROR)
            raise
        self.set(State.DISCONNECTED)

    def lost(self, reason):
        # Do not tear down a live session's firewall on failure.
        self.error = reason
        self.set(State.ERROR)
