import time
t = time.strftime("%H:%M:%S")
hour = int(input("Enter time"))
if (hour>=0 and hour<12):
	print("Gud mornig Sir!")
elif(hour>=12 and hour<17):
	print("Good Aftrenooe Sir")
elif(hour<=17 and hour<24):
	print("Good Nit Sir")

 