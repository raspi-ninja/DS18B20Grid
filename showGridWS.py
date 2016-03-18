import re,os
from subprocess import Popen, PIPE
import time,threading
from twisted.internet import threads
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.web.server import Site
from twisted.web.static import File
from autobahn.twisted.websocket import WebSocketServerProtocol,WebSocketServerFactory, \
    listenWS
from twisted.internet import reactor,task
from twisted.internet.task import LoopingCall


try:
    import ujson as json
except ImportError:
    import json

busdata = {}

def sleep(delay):
    d = Deferred()
    reactor.callLater(delay, d.callback, None)
    return d
def LoadBusFromJSON():
    f = open('app/sensors.json','r')
    jsonarray = json.loads(f.read())
    buses = {}
    for bus in jsonarray.keys():
        for sensors in jsonarray[bus]:
            buses[sensors["ID"]] = sensors
    f.close()
    return buses

def getCPUtemperature():
    temp = float(open('/sys/class/thermal/thermal_zone0/temp','r').read())/1000
    temp = temp *1.8 +32
    return str(temp)

def DS18B20_Bus(pin,data):
        pins = [4,17,27,5,6,13,19,26,21]
        pins.reverse()
        pin = pins[int(pin)-1]
        busdata = []
        position = 0
        args = 'sudo ./DS18B20Scan -gpio {} -t {} -F'.format(pin,30).split(' ')
        process = Popen(args, stdout=PIPE)
        (results, err) = process.communicate()
        exit_code = process.wait()
        probes = re.findall('(\d{2}-\w{12} ):\s+(\d{0,2}).bits\s Temperature:\s(\d{1,3}.\d{1,4})', results)
        bus = pins.index(pin)+1
        #print probes
        for probe in probes:
            try:
               # print data[probe[0].replace(" ",'')]
                if data.has_key(probe[0].replace(" ",'')):
                    position=data[probe[0].replace(" ",'')]["Pos"]
                else:
                    position +=1
                    print probe, bus

                temperatureInfo = {"ID":probe[0].replace(" ",''),"Pos":position,"Bus":
                    bus,"Temperature": round(float(probe[2]),3)} #,'Time': time.time()
                if probe[2] !="185.0000":
                    busdata.append(temperatureInfo)
            except:
                pass
        return busdata

class PiTempGridProtocol(WebSocketServerProtocol):
    def onOpen(self):
        self.factory.register(self)

    def onMessage(self, payload, isBinary):
        if not isBinary:
            jsn = json.loads(payload)
            if "bus" in jsn.keys():
                if jsn["bus"] == "Start":
                    self.factory.startBus(jsn["bus_num"])
                if jsn["bus"] == "Save":
                    self.factory.saveBus(jsn["bus_num"])

    def connectionLost(self, reason):
        WebSocketServerProtocol.connectionLost(self, reason)
        self.factory.unregister(self)


class PiTempGridFactory(WebSocketServerFactory):

    def __init__(self, url, debug=False, debugCodePaths=False):
        WebSocketServerFactory.__init__(self, url, debug=debug, debugCodePaths=debugCodePaths)
        self.clients = []
        self.cputemp = 0
        self.buses = LoadBusFromJSON()
        self.d = []
        self.startBus(1)
        self.startBus(2)
        self.startBus(3)
        self.startBus(4)
        self.startBus(5)
        self.startBus(6)
        self.startBus(7)
        self.startBus(8)
        self.startBus(9)
        cputemp = task.LoopingCall(self.getcpu)
        cputemp.start(5)

        #for bus in range(1,10):

    def getcpu(self):
        print 'getting cpu'
        d = threads.deferToThread(getCPUtemperature)
        d.addCallback(self.sendcpu)

    def sendcpu(self,info):
        self.cputemp = info
        self.broadcast({"cpu_temp": info})
        print 'sending cpu:',info

    def register(self, client):

        if client not in self.clients:
            print("registered client {}".format(client.peer))
            self.clients.append(client)
            datas = []
            for buskey in self.buses.keys():
                datas.append(self.buses[buskey])
            client.sendMessage(json.dumps(datas))
            client.sendMessage(json.dumps({"cput_temp":self.cputemp}))


    def unregister(self, client):
        if client in self.clients:
            print("unregistered client {}".format(client.peer))
            self.clients.remove(client)

    def broadcast(self, msg):
        preparedMsg = self.prepareMessage(json.dumps(msg))
        for c in self.clients:
            c.sendPreparedMessage(preparedMsg)
            #print("prepared message sent to {}".format(c.peer))

    def startBus(self,bus):
        if bus not in self.d:
            self.d.append(bus)
            d = threads.deferToThread(DS18B20_Bus,bus,self.buses)
            d.addCallback(self.sendBusData,bus)
            print 'starting',bus
        else:
            print 'already started',bus

    def sendBusData(self,datas,bus):
        newdatas = []
        for data in datas:
            if not self.buses.has_key(data["ID"]):
                self.buses[data["ID"]] = data
                newdatas.append(self.buses[data["ID"]])
                print 'new "{}"'.format(data["ID"])
            elif data["Temperature"] != self.buses[data["ID"]]["Temperature"]:
                self.buses[data["ID"]]["Temperature"]=data["Temperature"]
                newdatas.append(self.buses[data["ID"]])
                #print 'changed',data
        if len(newdatas) > 0:
            self.broadcast(datas)
        d = threads.deferToThread(DS18B20_Bus,bus,self.buses)
        d.addCallback(self.sendBusData,bus)
        #self.buses.append(DS18B20_Bus(bus, self.broadcast))

if __name__ == '__main__':
    factory = PiTempGridFactory(u"ws://127.0.0.1:9000")
    factory.protocol = PiTempGridProtocol
    listenWS(factory)
    webdir = File("app/")
    web = Site(webdir)
    reactor.listenTCP(80, web)
    reactor.run()
    #for bus in factory.buses:
    #    bus.loop=False
    #    #bus.join()