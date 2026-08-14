class Node:
    def __init__(self, value=None):
        self.data = value
        self.next = None
        self.prev = None

class DoublyLL:
    def __init__(self):
        self.head = None
        
    def insertAtEnd(self, value):
        temp = Node(value)
        if self.head is None:
            self.head = temp
            return
        
        t1 = self.head
        while t1.next is not None:
            t1 = t1.next
        
        t1.next = temp
        temp.prev = t1
   
    def insertAtBeg(self,value):
    	tamp = Node(value)
    	if self.head == None:
    		self.head = tamp
    		return
    	tamp.next = self.head
    	self.head.prve = tamp
    	self.head = tamp

    def printDLL(self):
        t1 = self.head
        while t1 is not None:
            print(t1.data, end=" <---> ")
            t1 = t1.next
        print("None")
obj = DoublyLL()
obj.insertAtEnd(10)
obj.insertAtEnd(20)
obj.insertAtEnd(30)
obj.insertAtEnd(40)
obj.insertAtBeg(5)
obj.printDLL()

