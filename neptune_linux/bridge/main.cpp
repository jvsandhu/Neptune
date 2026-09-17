// MIT; native Proton bridge. No CLR, managed assemblies, or browser runtime.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <tlhelp32.h>
#include <xinput.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
using Bytes = std::vector<unsigned char>;
using Address = std::uint64_t;
static constexpr size_t MAX_FRAME = 20 * 1024 * 1024;
// Bumped when the wire protocol changes; the client refuses a helper it cannot speak to.
static constexpr int PROTOCOL = 1;
static std::string utf8(const wchar_t* input) {
    int n = WideCharToMultiByte(CP_UTF8, 0, input, -1, nullptr, 0, nullptr, nullptr);
    if (n < 1) return "";
    std::string out(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, input, -1, out.data(), n, nullptr, nullptr);
    out.pop_back(); return out;
}
static std::string hex(const Bytes& bytes) {
    static const char* digits = "0123456789abcdef";
    std::string out; out.reserve(bytes.size()*2);
    for (auto byte : bytes) { out += digits[byte >> 4]; out += digits[byte & 15]; }
    return out;
}
static Bytes unhex(const std::string& text) {
    if (text.size()%2) throw std::runtime_error("Invalid hexadecimal length");
    auto digit = [](char c) -> int {
        if (c >= '0' && c <= '9') return c-'0';
        if (c >= 'a' && c <= 'f') return c-'a'+10;
        if (c >= 'A' && c <= 'F') return c-'A'+10;
        throw std::runtime_error("Invalid hexadecimal byte");
    };
    Bytes out; out.reserve(text.size()/2);
    for(size_t i=0;i<text.size();i+=2) out.push_back((digit(text[i])<<4)|digit(text[i+1]));
    return out;
}
static Address number(const std::string& value, int base=16) {
    size_t n=0; auto result=std::stoull(value,&n,base);
    if(n!=value.size()) throw std::runtime_error("Invalid number");
    return result;
}
static std::string addr(Address value) { std::ostringstream out; out << std::hex << value; return out.str(); }
static void fail(const char* action) { throw std::runtime_error(std::string(action)+" (Windows error "+std::to_string(GetLastError())+")"); }
class Game {
    HANDLE process=nullptr;
    DWORD attached_pid=0;
    struct Patch { Bytes original, latest; };
    std::map<Address,Patch> patches;
    std::vector<Address> order;
public:
    ~Game() { try { restore(); } catch (...) {} if(process) CloseHandle(process); }
    bool alive() const { return process && WaitForSingleObject(process,0)==WAIT_TIMEOUT; }
    void check() const { if(!alive()) throw std::runtime_error("Game is not attached or has exited"); }
    Bytes read(Address address, size_t length) {
        check(); if(!length || length>8*1024*1024) throw std::runtime_error("Read size outside 1..8 MiB");
        Bytes bytes(length); SIZE_T got=0;
        if(!ReadProcessMemory(process,reinterpret_cast<void*>(address),bytes.data(),length,&got) || got!=length) fail("ReadProcessMemory");
        return bytes;
    }
    void write(Address address,const Bytes& bytes) {
        check(); if(bytes.empty()) throw std::runtime_error("Empty write");
        // Data writes land on already-writable pages, so try the plain write first. Only
        // escalate to PAGE_EXECUTE_READWRITE when the page is not writable (code/const), and
        // put the old protection back. Forcing RWX on every write made game data executable,
        // paid two extra syscalls each time, and could leave an RWX page behind on a crash.
        SIZE_T written=0;
        if(WriteProcessMemory(process,reinterpret_cast<void*>(address),bytes.data(),bytes.size(),&written) && written==bytes.size())
            return;
        DWORD saved=GetLastError(), old=0;
        if(!VirtualProtectEx(process,reinterpret_cast<void*>(address),bytes.size(),PAGE_EXECUTE_READWRITE,&old)) {
            SetLastError(saved); fail("WriteProcessMemory");
        }
        BOOL ok=WriteProcessMemory(process,reinterpret_cast<void*>(address),bytes.data(),bytes.size(),&written);
        DWORD writeError=GetLastError(), ignored=0;
        BOOL restored=VirtualProtectEx(process,reinterpret_cast<void*>(address),bytes.size(),old,&ignored);
        FlushInstructionCache(process,reinterpret_cast<void*>(address),bytes.size());
        if(!ok || written!=bytes.size()) { SetLastError(writeError); fail("WriteProcessMemory"); }
        if(!restored) fail("Restore page protection");
    }
    void patch(Address address,const Bytes& expected,const Bytes& replacement) {
        if(expected.empty() || expected.size()!=replacement.size()) throw std::runtime_error("Patch lengths differ");
        if(read(address,expected.size())!=expected) throw std::runtime_error("Target changed; refusing stale patch");
        auto it=patches.find(address);
        if(it==patches.end()) {
            for(const auto& entry:patches)
                if(address<entry.first+entry.second.original.size() && entry.first<address+expected.size())
                    throw std::runtime_error("Overlapping tracked patch");
            patches.emplace(address,Patch{expected,replacement}); order.push_back(address);
        } else {
            if(it->second.original.size()!=replacement.size()) throw std::runtime_error("Tracked patch size changed");
            it->second.latest=replacement;
        }
        write(address,replacement);
    }
    void restore_one(Address address) {
        auto it=patches.find(address); if(it==patches.end()) return;
        auto current=read(address,it->second.original.size());
        if(current!=it->second.latest && current!=it->second.original) throw std::runtime_error("Tracked target changed; restore refused");
        if(current!=it->second.original) write(address,it->second.original);
        patches.erase(it);
    }
    void restore() {
        if(!alive()) { patches.clear(); order.clear(); return; }
        std::string errors;
        for(auto it=order.rbegin();it!=order.rend();++it) {
            try { restore_one(*it); } catch(const std::exception& e) { errors+=addr(*it)+": "+e.what()+"; "; }
        }
        if(!errors.empty()) throw std::runtime_error(errors);
        order.clear();
    }
    std::string attach(DWORD pid) {
        if(process) throw std::runtime_error("Disconnect before attaching another process");
        HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
        if(snapshot==INVALID_HANDLE_VALUE) fail("Process snapshot");
        PROCESSENTRY32W entry{}; entry.dwSize=sizeof(entry); bool found=false;
        if(Process32FirstW(snapshot,&entry)) do {
            if(entry.th32ProcessID==pid && (_wcsicmp(entry.szExeFile,L"ForzaHorizon6.exe")==0 || _wcsicmp(entry.szExeFile,L"ForzaHorizon6")==0)) {found=true;break;}
        }while(Process32NextW(snapshot,&entry));
        CloseHandle(snapshot);
        if(!found) throw std::runtime_error("Selected PID is not ForzaHorizon6.exe");
        HANDLE handle=OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ|PROCESS_VM_WRITE|PROCESS_VM_OPERATION|PROCESS_CREATE_THREAD|SYNCHRONIZE,FALSE,pid);
        if(!handle) fail("OpenProcess");
        snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE|TH32CS_SNAPMODULE32,pid);
        if(snapshot==INVALID_HANDLE_VALUE) {CloseHandle(handle);fail("Module snapshot");}
        MODULEENTRY32W module{};module.dwSize=sizeof(module);
        bool ok=Module32FirstW(snapshot,&module); CloseHandle(snapshot);
        if(!ok) {CloseHandle(handle);fail("Module32First");}
        process=handle;attached_pid=pid;
        return addr(reinterpret_cast<Address>(module.modBaseAddr))+" "+std::to_string(module.modBaseSize)+" "+utf8(module.szModule);
    }
    Address allocate(Address target,size_t size) {
        check(); if(size==0 || size>8*1024*1024) throw std::runtime_error("Invalid allocation size");
        if(!target) { auto p=VirtualAllocEx(process,nullptr,size,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE); if(!p) fail("VirtualAllocEx"); return reinterpret_cast<Address>(p); }
        Address aligned=target&~Address(0xffff);
        for(Address delta=0;delta<=0x70000000;delta+=0x10000) {
            Address candidates[]={aligned>delta?aligned-delta:0,aligned+delta};
            for(auto candidate:candidates) {
                if(candidate<0x10000 || candidate>=0x7fffffff0000) continue;
                auto p=VirtualAllocEx(process,reinterpret_cast<void*>(candidate),std::max<size_t>(size,0x1000),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
                if(p) return reinterpret_cast<Address>(p);
            }
        }
        throw std::runtime_error("No free executable memory near hook");
    }
    std::string maps() {
        check(); MEMORY_BASIC_INFORMATION info{}; Address cursor=0; std::ostringstream result;
        while(VirtualQueryEx(process,reinterpret_cast<void*>(cursor),&info,sizeof(info))) {
            auto base=reinterpret_cast<Address>(info.BaseAddress);
            if(info.State==MEM_COMMIT && !(info.Protect&PAGE_GUARD) && (info.Protect&0xff)!=PAGE_NOACCESS)
                result<<addr(base)<<" "<<info.RegionSize<<" "<<info.Protect<<" "<<info.Type<<"\n";
            Address next=base+info.RegionSize; if(next<=cursor) break; cursor=next;
        }
        return result.str();
    }
    std::string input() {
        check(); DWORD foreground=0;GetWindowThreadProcessId(GetForegroundWindow(),&foreground);
        Bytes keys(32,0);
        for(int key=0;key<256;++key) if(GetAsyncKeyState(key)&0x8000) keys[key/8]|=static_cast<unsigned char>(1U<<(key%8));
        return std::string(foreground==attached_pid?"1 ":"0 ")+hex(keys);
    }
    std::string driving_input() {
        // Keep INPUT unchanged for older clients and read-only diagnostics.
        std::string keyboard = input();
        using GetState = DWORD (WINAPI *)(DWORD, XINPUT_STATE*);
        static GetState getState = []() -> GetState {
            for (const char* name : {"xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"}) {
                HMODULE module = LoadLibraryA(name);
                if (!module) continue;
                FARPROC address = GetProcAddress(module, "XInputGetState");
                if (address) {
                    GetState function = nullptr;
                    static_assert(sizeof(function) == sizeof(address));
                    std::memcpy(&function, &address, sizeof(function));
                    return function;
                }
                FreeLibrary(module);
            }
            return nullptr;
        }();
        static ULONGLONG retryAfter[XUSER_MAX_COUNT] = {};
        unsigned mask = 0, left = 0, right = 0;
        const auto now = GetTickCount64();
        if (getState) for (DWORD index = 0; index < XUSER_MAX_COUNT; ++index) {
            if (now < retryAfter[index]) continue;
            XINPUT_STATE state{};
            if (getState(index, &state) != ERROR_SUCCESS) {
                retryAfter[index] = now + 1000;
                continue;
            }
            mask |= 1U << index;
            left = std::max(left, static_cast<unsigned>(state.Gamepad.bLeftTrigger));
            right = std::max(right, static_cast<unsigned>(state.Gamepad.bRightTrigger));
        }
        return keyboard + " " + std::to_string(mask) + " " +
            std::to_string(left) + " " + std::to_string(right);
    }
    std::string neptune_input() {
        std::string result = input();
        static ULONGLONG retryAfter[XUSER_MAX_COUNT] = {};
        const auto now = GetTickCount64();
        for (DWORD index = 0; index < XUSER_MAX_COUNT; ++index) {
            XINPUT_STATE state{};
            if (now < retryAfter[index] || XInputGetState(index, &state) != ERROR_SUCCESS) {
                if (now >= retryAfter[index]) retryAfter[index] = now + 1000;
                result += " 0,0,0,0";
            } else {
                result += " 1," + std::to_string(state.Gamepad.wButtons) + "," +
                    std::to_string(state.Gamepad.bLeftTrigger) + "," + std::to_string(state.Gamepad.bRightTrigger);
            }
        }
        return result;
    }
    DWORD execute(const Bytes& code) {
        check(); if(code.empty() || code.size()>65536) throw std::runtime_error("Invalid remote code size");
        Address buffer=allocate(0,code.size());
        bool running=false;
        try {
            write(buffer,code);
            HANDLE thread=CreateRemoteThread(process,nullptr,0,reinterpret_cast<LPTHREAD_START_ROUTINE>(buffer),nullptr,0,nullptr);
            if(!thread)fail("CreateRemoteThread");
            running=true; DWORD wait=WaitForSingleObject(thread,15000),result=0;
            BOOL got=GetExitCodeThread(thread,&result);CloseHandle(thread);
            if(wait!=WAIT_OBJECT_0)throw std::runtime_error("Remote operation completion uncertain; do not retry automatically");
            running=false;if(!got)fail("GetExitCodeThread");
            VirtualFreeEx(process,reinterpret_cast<void*>(buffer),0,MEM_RELEASE);return result;
        }catch(...) {if(!running)VirtualFreeEx(process,reinterpret_cast<void*>(buffer),0,MEM_RELEASE);throw;}
    }
    Address query(Address function,Address database,const Bytes& sql) {
        if(sql.empty() || sql.size()>1024*1024) throw std::runtime_error("Invalid SQL length");
        Bytes text=sql;text.push_back(0);
        Address storage=allocate(0,text.size()+4096), result=storage+text.size()+16, code=result+16;
        auto release=[&](){VirtualFreeEx(process,reinterpret_cast<void*>(storage),0,MEM_RELEASE);};
        try {
            write(storage,text);write(result,Bytes(8,0));
            Bytes shell={0x48,0xba,0,0,0,0,0,0,0,0,0x49,0xb8,0,0,0,0,0,0,0,0,0xff,0x25,0,0,0,0,0,0,0,0,0,0,0,0};
            std::memcpy(shell.data()+2,&result,8);std::memcpy(shell.data()+12,&storage,8);std::memcpy(shell.data()+26,&function,8);
            write(code,shell);
            HANDLE thread=CreateRemoteThread(process,nullptr,0,reinterpret_cast<LPTHREAD_START_ROUTINE>(code),reinterpret_cast<void*>(database),0,nullptr);
            if(!thread) fail("CreateRemoteThread");
            DWORD wait=WaitForSingleObject(thread,15000),exitCode=0;
            BOOL got=GetExitCodeThread(thread,&exitCode);CloseHandle(thread);
            // Leave pages mapped on timeout: the game thread may still execute them.
            if(wait!=WAIT_OBJECT_0) {storage=0;throw std::runtime_error("SQL completion uncertain; do not retry blindly");}
            if(!got) throw std::runtime_error("Could not read SQL thread status");
            // CDatabase returns a result pointer; a nonzero thread return is not itself an error.
            auto bytes=read(result,8);Address pointer=0;std::memcpy(&pointer,bytes.data(),8);release();return pointer;
        }catch(...) {if(storage) release();throw;}
    }
};
static std::string list_games() {
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);if(snapshot==INVALID_HANDLE_VALUE)fail("Process snapshot");
    PROCESSENTRY32W item{};item.dwSize=sizeof(item);std::ostringstream result;
    if(Process32FirstW(snapshot,&item))do {
        if(_wcsicmp(item.szExeFile,L"ForzaHorizon6.exe")==0 || _wcsicmp(item.szExeFile,L"ForzaHorizon6")==0)
            result<<item.th32ProcessID<<"\t"<<utf8(item.szExeFile)<<"\n";
    }while(Process32NextW(snapshot,&item));
    CloseHandle(snapshot);return result.str();
}
static bool transfer(SOCKET socket,char* data,size_t length,bool sending) {
    while(length) {int n=sending?send(socket,data,static_cast<int>(length),0):recv(socket,data,static_cast<int>(length),0);if(n<=0)return false;data+=n;length-=n;}return true;
}
static bool frame(SOCKET socket,std::string& data,bool sending) {
    uint32_t length=static_cast<uint32_t>(data.size());
    if(!transfer(socket,reinterpret_cast<char*>(&length),4,sending))return false;
    if(length>MAX_FRAME)return false;
    if(!sending)data.resize(length);
    return transfer(socket,data.data(),length,sending);
}
int main(int argc,char** argv) {
    if(argc==2 && std::string(argv[1])=="--self-test") {
        if(hex(unhex("00ff1234"))!="00ff1234")return 1;
        std::cout<<"Neptune C++ bridge; protocol "<<PROTOCOL<<"; no CLR\n";return 0;
    }
    if(argc!=3) {std::cerr<<"Usage: neptune-bridge.exe PORT TOKEN\n";return 2;}
    try {
        auto port=number(argv[1],10);if(port<1024 || port>65535 || std::strlen(argv[2])!=64)return 2;
        WSADATA data{};if(WSAStartup(MAKEWORD(2,2),&data))return 3;
        SOCKET socket=::socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(socket==INVALID_SOCKET)return 3;
        sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(static_cast<u_short>(port));address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
        if(connect(socket,reinterpret_cast<sockaddr*>(&address),sizeof(address))==SOCKET_ERROR){closesocket(socket);WSACleanup();return 4;}
        std::string hello=std::string("LUNA1 ")+std::to_string(PROTOCOL)+" "+argv[2];if(!frame(socket,hello,true))return 4;
        { Game game;std::string request,lastOperation;
          std::cerr<<"Bridge connected; helper PID="<<GetCurrentProcessId()<<"\n";
          while(frame(socket,request,false)) {
            std::istringstream in(request);std::string operation,a,b,c;in>>operation>>a>>b>>c;lastOperation=operation;std::string response;
            try {
                std::string value;
                if(operation=="LIST")value=list_games();
                else if(operation=="ATTACH")value=game.attach(static_cast<DWORD>(number(a,10)));
                else if(operation=="ALIVE")value=game.alive()?"1":"0";
                else if(operation=="READ")value=hex(game.read(number(a),number(b,10)));
                else if(operation=="WRITE")game.write(number(a),unhex(b));
                else if(operation=="PATCH")game.patch(number(a),unhex(b),unhex(c));
                else if(operation=="RESTORE") {if(a.empty())game.restore();else game.restore_one(number(a));}
                else if(operation=="ALLOC")value=addr(game.allocate(number(a),number(b,10)));
                else if(operation=="MAPS")value=game.maps();
                else if(operation=="INPUT")value=game.input();
                else if(operation=="INPUT2")value=game.driving_input();
                else if(operation=="NEPTUNE_INPUT")value=game.neptune_input();
                else if(operation=="EXEC")value=std::to_string(game.execute(unhex(a)));
                else if(operation=="QUERY")value=addr(game.query(number(a),number(b),unhex(c)));
                else if(operation=="KEY") {auto key=number(a,10);if(key>255)throw std::runtime_error("Invalid key");value=(GetAsyncKeyState(static_cast<int>(key))&0x8000)?"1":"0";}
                else if(operation=="CLOSE") {game.restore();response="OK ";frame(socket,response,true);break;}
                else throw std::runtime_error("Unknown operation");
                response="OK "+value;
            }catch(const std::exception& error) {std::cerr<<"Operation "<<operation<<" failed: "<<error.what()<<"\n";response=std::string("ERR ")+error.what();}
            if(!frame(socket,response,true)){std::cerr<<"Response send failed after "<<operation<<"; socket error="<<WSAGetLastError()<<"\n";break;}
          }
          std::cerr<<"Bridge session ending; last operation="<<lastOperation<<"; game alive="<<game.alive()<<"\n";
        }
        closesocket(socket);WSACleanup();return 0;
    }catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
