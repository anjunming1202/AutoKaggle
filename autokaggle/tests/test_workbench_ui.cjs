"use strict";
const {test}=require("node:test"), assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path"), vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../static/workbench.js"),"utf8");
const flush=async()=>{for(let i=0;i<5;i++)await new Promise(setImmediate);};
function fixture(){return {
  project:{title:"Saved material challenge",design:{metric:"accuracy",target:"stable",split:"group"}},
  conversation:{status:"idle",readme:"Saved README",storage:{required:false},setup:{competition_type:"prediction",submissions_confirmed:true,daily_submission_limit:5},checklist:[{id:"question",label:"Scientific question",value:"Predict survival",requirements:[{label:"Success",value:"0.8",status:"bypassed",bypass:{reason:"An exploratory pilot."}}]}]},
  workflow:{version:"v1",status:"ready_for_review",website_url:"/api/projects/p1/workflow/preview",download_url:"/api/projects/p1/workflow/package",submission_url:"/api/projects/p1/workflow/preview#submission",first_result:{metric:"accuracy",score:0.75},checks:[{label:"Scorer",detail:"Measured pipeline check",status:"pass"}]},
  attempts:{attempts:[{version:"v1",day:"2026-11-04",result:{status:"scored",metric:"accuracy",score:0.7,detail:"Development only"}}]}
};}
function harness(data=fixture(),search="?project=p1&view=review",getHandler=null){
 const nodes=new Map(),calls=[],redirects=[],listeners={},storage=new Map();
 class Node{constructor(tag){this.tag=tag;this.value="";this.hidden=false;this.disabled=false;this.children=[];this.attributes={};this.events={};this._text="";}set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent).join(" ");}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;this._text="";}setAttribute(k,v){this.attributes[k]=String(v);}removeAttribute(k){delete this.attributes[k];delete this[k];}addEventListener(k,v){this.events[k]=v;}focus(){this.focused=true;}}
 const $=id=>{if(!nodes.has(id))nodes.set(id,new Node("div"));return nodes.get(id);};
 const location={origin:"https://testserver",search,assign:url=>redirects.push(url),replace:url=>redirects.push(url)};
 const h={$,calls,redirects,listeners,storage,data,fail:null,posts:[],handler:null,async click(id){if(!$(id).disabled)await $(id).events.click();await flush();}};
 const fetch=async(url,options)=>{
  calls.push({url,options});
  let body;
  if(options.method){h.posts.push({url,options});if(h.handler)return h.handler(url,options);body={review:{mode:"revision"}};}
  else if(getHandler)return getHandler(url,options);
  else if(url==="/api/access")body={auth_kind:"anonymous"};
  else if(h.fail)return {ok:false,status:h.fail,json:async()=>({detail:"Sign-in expired."})};
  else body=url.endsWith("/conversation")?data.conversation:url.endsWith("/workflow")?data.workflow:url.endsWith("/attempts")?data.attempts:data.project;
  return {ok:true,json:async()=>body};
 };
 vm.runInNewContext(source,{document:{getElementById:$,createElement:tag=>new Node(tag)},location,window:{addEventListener:(k,v)=>listeners[k]=v},URL,URLSearchParams,AbortSignal,fetch,crypto:{randomUUID:()=>"stable-review-request"},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}});
 return h;
}
test("Review loads saved artifacts and results without creating or changing anything",async()=>{
 const h=harness();await flush();assert.equal(h.calls.length,4);assert.ok(h.calls.every(c=>!c.options.method));assert.equal(h.$("challenge-title").textContent,"Saved material challenge");assert.equal(h.$("website-link").href,"/api/projects/p1/workflow/preview");assert.equal(h.$("request-changes").disabled,false);assert.match(h.$("definition").textContent,/Organizer bypass: An exploratory pilot/);assert.match(h.$("attempts").textContent,/0.7/);assert.match(h.$("first-result").textContent,/separate from a reproduced scientific baseline/);
});
test("Environment review preserves the approval gate and states the trial limit",async()=>{
 const f=fixture();f.conversation.setup.competition_type="environment";f.workflow.status="awaiting_approval";f.workflow.first_result={kind:"environment_mechanism_test",metric:"success_rate",score:0.5};
 const h=harness(f);await flush();assert.match(h.$("notice").textContent,/Waiting for administrator approval/);assert.match(h.$("setup-summary").textContent,/Environment policy repository/);assert.match(h.$("first-result").textContent,/built-in toy environment/);assert.match(h.$("first-result").textContent,/submitted policy were not run/);assert.equal(h.posts.length,0);
});
for(const search of ["","?project=p1","?view=review"])test(`A normal opening returns to the agent: ${search}`,async()=>{
 const h=harness(fixture(),search);await flush();assert.equal(h.calls.length,0);assert.deepEqual(h.redirects,[search.includes("project=p1")?"/?project=p1":"/"]);
});
test("Stale packages hide every artifact and explain the rebuild",async()=>{
 const f=fixture();f.workflow.status="stale";const h=harness(f);await flush();for(const k of ["website","package","submission"]){assert.equal(h.$(k+"-link").hidden,true);assert.equal(h.$(k+"-link").href,undefined);}assert.match(h.$("notice").textContent,/out of date/);
});
test("Artifact links cannot send a reviewer to another origin or endpoint",async()=>{
 const f=fixture();f.workflow.website_url="https://other.example.org/";f.workflow.download_url="javascript:alert(1)";f.workflow.submission_url="/api/projects/other/workflow/preview";const h=harness(f);await flush();for(const k of ["website","package","submission"])assert.equal(h.$(k+"-link").hidden,true);
});
test("Request changes starts the existing review workflow and opens the same project in the agent",async()=>{
 const h=harness();await flush();await h.click("request-changes");assert.equal(h.posts[0].url,"/api/projects/p1/iterate");assert.deepEqual(JSON.parse(h.posts[0].options.body),{request_id:"stable-review-request"});assert.deepEqual(h.redirects,["/?project=p1"]);
});
test("A lost revision response retries the same request identity",async()=>{
 const h=harness();await flush();h.handler=async()=>{throw new TypeError("Connection stopped.");};await h.click("request-changes");assert.equal(h.$("request-changes").disabled,false);h.handler=null;await h.click("request-changes");assert.equal(h.posts.length,2);assert.equal(h.posts[0].options.body,h.posts[1].options.body);
});
test("A pending revision request blocks duplicate clicks",async()=>{
 const h=harness();await flush();let release;h.handler=()=>new Promise(resolve=>{release=resolve;});const pending=h.click("request-changes");await flush();await h.click("request-changes");assert.equal(h.posts.length,1);release({ok:true,json:async()=>({})});await pending;
});
test("Expired access clears the old private snapshot and keeps the intended review destination",async()=>{
 const h=harness();await flush();h.fail=404;await h.click("refresh");assert.equal(h.$("challenge-title").textContent,"Review unavailable");assert.equal(h.$("checks").children.length,0);assert.equal(h.$("request-changes").disabled,true);assert.equal(h.$("sign-in").hidden,false);assert.equal(h.$("sign-in").href,"/login?next="+encodeURIComponent("/workbench?project=p1&view=review"));
});
test("Cross-tab sign-out clears private content and disables changes",async()=>{
 const h=harness();await flush();h.listeners.storage({key:"autokaggle-session-ended"});assert.equal(h.$("challenge-title").textContent,"Review unavailable");assert.equal(h.$("request-changes").disabled,true);assert.equal(h.$("website-link").hidden,true);
});
test("An unbuilt challenge goes back to the interview",async()=>{
 const f=fixture();delete f.workflow.version;const h=harness(f);await flush();assert.deepEqual(h.redirects,["/?project=p1"]);
});
test("Storage acceptance is done in the agent before starting a revision",async()=>{
 const f=fixture();f.conversation.storage.required=true;const h=harness(f);await flush();assert.equal(h.$("request-changes").disabled,true);assert.match(h.$("feedback-detail").textContent,/storage notice/);
});
test("Review tabs support keyboard navigation",async()=>{
 const h=harness();await flush();h.$("tab-overview").events.keydown({key:"End",preventDefault(){}});assert.equal(h.$("panel-overview").hidden,true);assert.equal(h.$("panel-attempts").hidden,false);assert.equal(h.$("tab-attempts").focused,true);
});

test("Late responses cannot restore the old private snapshot after account change",async()=>{
 const held=[],f=fixture();
 const h=harness(f,"?project=p1&view=review",url=>new Promise(resolve=>held.push({url,resolve})));
 await flush();h.listeners.storage({key:"autokaggle-session-ended"});
 for(const request of held){const body=request.url.endsWith("/conversation")?f.conversation:request.url.endsWith("/workflow")?f.workflow:request.url.endsWith("/attempts")?f.attempts:f.project;request.resolve({ok:true,json:async()=>body});}
 await flush();assert.equal(h.$("challenge-title").textContent,"Review unavailable");assert.equal(h.$("request-changes").disabled,true);assert.equal(h.$("website-link").hidden,true);
});
