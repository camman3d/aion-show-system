import sacn


class DmxOutput:
    def output(self, universe, channel, value):
        pass

    def stop(self):
        pass


class SacnOutput(DmxOutput):
    def __init__(self, host) -> None:
        self.sender = sacn.sACNsender()
        self.sender.start()
        self.host = host
        self.data = {}

    def output(self, universe, channel, value):
        if universe not in self.data.keys():
            self.sender.activate_output(universe)
            self.sender[universe].destination = self.host
            self.data[universe] = [0]

        channel -= 1  # sACN begins at 1, which corresponds to index 0
        while channel >= len(self.data[universe]):
            self.data[universe].append(0)
        self.data[universe][channel] = value
        self.sender[universe].dmx_data = tuple(self.data[universe])
    
    def stop(self):
        self.sender.stop()



output_device = DmxOutput()

def configure_dmx(protocol, host):
    global output_device
    if protocol == "sacn":
        output_device = SacnOutput(host)
    else:
        print(f"Unknown DMX output protocol '{protocol}. DMX not configured")
