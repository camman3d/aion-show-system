import sacn
import time

sender = sacn.sACNsender()  # provide an IP-Address to bind to if you want to send multicast packets from a specific interface
sender.start()  # start the sending thread
sender.activate_output(1)  # start sending out data in the 1st universe
sender[1].destination = "192.168.2.190"  # or provide unicast information.
# Keep in mind that if multicast is on, unicast is not used
sender[1].dmx_data = (255, 255, 255, 255)  # some test DMX data

time.sleep(3)  # send the data for 10 seconds
sender.stop()  # do not forget to stop the sender