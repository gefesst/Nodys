"""Reject responses belonging to an old screen or authentication session."""
class RequestScope:
    def __init__(self):
        self.epoch = 0
        self.serials = {}

    def invalidate(self):
        self.epoch += 1
        self.serials.clear()

    def capture(self, action, identity):
        serial = self.serials.get(action, 0) + 1
        self.serials[action] = serial
        return self.epoch, action, serial, identity

    def accepts(self, ticket, identity):
        epoch, action, serial, original_identity = ticket
        return (epoch == self.epoch and identity == original_identity
                and self.serials.get(action) == serial)
