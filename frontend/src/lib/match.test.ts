import { describe, expect, it } from 'vitest'
import type { CommandRef } from './data'
import { equivalentCommand, exact, normCommand, ocEquivalent } from './match'

const ref = (cmd: string): CommandRef => ({ cmd, meaning: '', lab: 'l', lab_title: 'L', kind: 'lab', as: 'learner', run: null, stdout: 'x', stderr: '', code: 0, tested: true, skip: '' })

describe('kubectl and oc in the practice terminal', () => {
  it('maps only plain Kubernetes commands to an oc recording, and says so', () => {
    expect(ocEquivalent('kubectl  get pods')).toBe('oc get pods')
    expect(ocEquivalent('kubectl new-project demo')).toBeNull()
    expect(ocEquivalent('kubectl expose deployment web')).toBeNull() // creates a Service, not a Route as oc expose does
    expect(ocEquivalent('kubectl create route edge x')).toBeNull()
    const m = exact([ref('oc get pods')], 'kubectl get pods')
    expect(m?.viaOc).toBe(true)
    expect(exact([ref('oc get pods')], 'oc get pods')?.viaOc).toBeUndefined()
    expect(exact([ref('oc new-project demo')], 'kubectl new-project demo')).toBeUndefined()
  })
})

describe('normCommand', () => {
  it('collapses spacing outside quotes only', () => {
    expect(normCommand('ls   -l  "My Report.txt" ')).toBe('ls -l "My Report.txt"')
    expect(normCommand('ls -l "My  Report.txt"')).not.toBe(normCommand('ls -l "My Report.txt"'))
    expect(normCommand("grep -c '  500  ' access.log")).not.toBe(normCommand("grep -c ' 500 ' access.log"))
  })
  it('makes spacing around pipes and separators uniform', () => {
    expect(normCommand('grep INFO logs/app.log|wc -l')).toBe(normCommand('grep INFO logs/app.log | wc -l'))
    expect(normCommand('cd notes&&ls')).toBe(normCommand('cd notes && ls'))
    expect(normCommand('false||echo no')).toBe(normCommand('false || echo no'))
    expect(normCommand("echo 'a|b'")).toBe("echo 'a|b'")
    expect(normCommand('ls;')).toBe('ls')
  })
})

describe('a path is compared as typed', () => {
  it('never takes a changed path for the accepted one', () => {
    for (const [typed, accepted] of [['cat ./readme.txt', 'cat ../readme.txt'], ['cat .readme.txt', 'cat ../readme.txt'], ['echo rm logs *.txt', 'echo rm logs/*.txt'], ['echo rm logs*.txt', 'echo rm logs/*.txt']])
      expect(equivalentCommand(typed, accepted) || normCommand(typed) === normCommand(accepted)).toBe(false)
    expect(equivalentCommand('cat ./../readme.txt', 'cat ../readme.txt')).toBe(true)
  })
})

describe('equivalentCommand', () => {
  const ok = (a: string, b: string) => expect(equivalentCommand(a, b)).toBe(true)
  const no = (a: string, b: string) => expect(equivalentCommand(a, b)).toBe(false)
  it('accepts option order, grouping and path spelling', () => {
    ok('ls -al', 'ls -la')
    ok('ls -l -a', 'ls -la')
    ok('ls -a  -l .', 'ls -la .')
    ok('cp -r ./notes notes-copy', 'cp -r notes notes-copy')
    ok('cd ./notes/', 'cd notes')
    ok('cat -n ./notes/todo.txt', 'cat -n notes/todo.txt')
    ok('mkdir old/ archive/', 'mkdir old archive')
    ok("find project -name \"*.log\"", "find project -name '*.log'")
  })
  it('rejects what changes the meaning', () => {
    no('ls -la practice', 'ls -la')
    no('rm -rf notes-copy', 'rm -r notes-copy')
    no('cp notes-copy notes -r', 'cp -r notes notes-copy')
    no('mkdir archive old', 'mkdir old archive')
    no('find project -name *.log', "find project -name '*.log'")
    no('head file -n 2', 'head -n 2 file')
    no('oc exec deploy/x -- ls -l /tmp', 'oc exec deploy/x -- ls -la /tmp')
    no('grep -q ERROR app.log || echo none', 'grep -q ERROR app.log || echo "none"')
    no('ls; rm -r notes', 'ls')
  })
  it('stays strict where it does not know the program (final review)', () => {
    no('summarise.sh logs/app.log', './summarise.sh logs/app.log') // the program name is never normalised
    no('rsync -a site/ backup/', 'rsync -a site backup/') // a trailing slash changes what rsync copies
    no('cp notes notes-copy -r', 'cp -r notes notes-copy') // options do not move past operands
    no('podman run --name second busybox:latest sleep 1000 -d', 'podman run -d --name second busybox:latest sleep 1000')
    no('podman run --name site -p 18280:8080 localhost/site:1.0 -d', 'podman run -d --name site -p 18280:8080 localhost/site:1.0')
    no('podman build localhost/site:2.0 . -t', 'podman build -t localhost/site:2.0 .')
    no('git config diff -C', 'git -C config diff')
    no('journalctl --no-pager academy-crash --user-unit', 'journalctl --user-unit academy-crash --no-pager')
    no('tar -ftv site.tar.xz', 'tar -tvf site.tar.xz')
    no('find project -mane "*.log"', "find project -name '*.log'")
    no("find project -type '*.log' -name f", "find project -name '*.log' -type f")
    no('helm rollback payments 1 team-apps -n', 'helm rollback payments 1 -n team-apps')
    no('oc annotate svc api service.openshift.io/serving-cert-secret-name=api-tls', 'oc annotate svc api service.beta.openshift.io/serving-cert-secret-name=api-tls')
    no('oc annotate svc api svc/serving-cert-secret-name=api-tls', 'oc annotate svc api service.beta.openshift.io/serving-cert-secret-name=api-tls')
    no('oc get pvc.example.com', 'oc get pvc')
    no('cat -n notes/todo.txt/.', 'cat -n ./notes/todo.txt') // `x/.` needs a directory
    no('oc get pod worker-abc -n billing/. -o yaml', 'oc get pod worker-abc -n billing -o yaml') // values compared as typed
    ok('oc adm groups sync --sync-config ././payments-sync.yaml --confirm', 'oc adm groups sync --sync-config payments-sync.yaml --confirm')
    no('oc label pod web owner=deploy/x', 'oc label pod web owner=deployment/x') // kind spellings only in resource references
    ok('podman run -it --rm ubi9', 'podman run -i -t --rm ubi9')
  })
  it('keeps each option with its own value', () => {
    no('oc auth can-i list pods --as academy-auditors --as-group someone', 'oc auth can-i list pods --as someone --as-group academy-auditors')
    no('oc create rolebinding ci --serviceaccount deploy-patcher --role x:ci-deployer', 'oc create rolebinding ci --role deploy-patcher --serviceaccount x:ci-deployer')
    no('oc logs api-8 -n server -c billing --previous', 'oc logs api-8 -n billing -c server --previous')
    no('helm template preview lab/chart --set prod.yaml -f replicas=3', 'helm template preview lab/chart -f prod.yaml --set replicas=3')
    no('oc get pods -n x', 'oc get x -n pods')
    no('cmd --a x --b y', 'cmd --a y --b x')
    ok('oc set env deploy/web --env A=1 --env B=2', 'oc set env deploy/web --env B=2 --env A=1')
    ok('helm template p c --set a=1 -f v.yaml', 'helm template p c -f v.yaml --set a=1') // helm applies -f files before --set values, whatever their order
  })
  it('knows the oc and kubectl options that take a value', () => {
    ok('oc -n openshift-config get secret htpass', 'oc get secret htpass -n openshift-config')
    ok('oc get pdb checkout --namespace=payments --output yaml', 'oc get pdb checkout -n payments -o yaml')
    ok('oc get pdb checkout -n payments -oyaml', 'oc get pdb checkout -n payments -o yaml')
    ok('oc get pdb checkout -n payments -o=yaml', 'oc get pdb checkout -n payments -o yaml')
    ok('oc get nodes -owide', 'oc get nodes -o wide')
    ok('oc logs -c log-shipper deploy/app', 'oc logs deploy/app -c log-shipper')
    ok('oc create rolebinding ci --serviceaccount s --role r', 'oc create rolebinding ci --role r --serviceaccount s')
    ok('oc create role r --verb get --resource deploy', 'oc create role r --resource=deploy --verb=get')
    ok('oc extract secret/x --to=current/', 'oc extract secret/x --to current')
    ok("oc get deployment web -ojsonpath='{.spec.replicas}'", "oc get deployment web -o jsonpath='{.spec.replicas}'")
    ok("oc patch deploy web --patch='{\"spec\":{}}'", "oc patch deploy web -p '{\"spec\":{}}'".replace('-p', '--patch'))
    ok('oc set probe --readiness deployment/web --open-tcp=8080', 'oc set probe deployment/web --readiness --open-tcp=8080')
    ok('oc logs --all-pods deploy/checkout -n shop', 'oc logs deploy/checkout -n shop --all-pods')
    ok('oc set env deployment/settings --from=secrets/db', 'oc set env deployment/settings --from=secret/db')
    ok('oc exec -it deploy/toolbox -- getent hosts kubernetes.default', 'oc exec deploy/toolbox -i -t -- getent hosts kubernetes.default')
    ok('oc logs --previous api-8', 'oc logs api-8 -p')
    ok('kubectl get pods -A', 'kubectl get pods --all-namespaces')
    ok('oc get ev --field-selector involvedObject.name=ghost', 'oc get events --field-selector involvedObject.name=ghost')
    ok('oc rollout status deployment/web', 'oc rollout status deploy/web')
    ok('oc get statefulset.apps/web -o yaml', 'oc get sts/web -o yaml')
    ok('oc get clusteroperator.config.openshift.io', 'oc get co')
    ok('oc get servicemonitors.monitoring.coreos.com -n x', 'oc get servicemonitor -n x')
    ok('oc get deploy,svc', 'oc get deployments,services')
    ok('oc get deploy web -o yaml', 'oc get deployment/web -o yaml')
    ok('oc describe pod a b', 'oc describe pod/a pods/b')
    no('oc get deploy web', 'oc get deployment/db')
    no('oc label pod web app=x', 'oc label pod/web app=y')
    no('oc create deployments web --image=x', 'oc create deployment web --image=x') // create's subcommand is not a kind
    no('oc exec deploy/x -- getent hosts kubernetes.default', 'oc exec deploy/x -- getent hosts kubernetes')
    no('oc get pods -o yaml', 'oc get pods -o json')
    no('oc get pods -n a', 'oc get pods -n b')
    no('oc get pods', 'oc get pods -n x')
    no('oc exec deploy/x -- ls -l /tmp', 'oc exec deploy/x -- ls -la /tmp')
  })

  it('follows the shell: what bash expands is not what was typed literally', () => {
    // reported by a learner: bash turns `~` into the home directory, so oc receives `users /home/…` and refuses it
    no('oc get users ~', 'oc get user/~')
    no('oc get users ~', "oc get user '~'")
    no('oc get user ~', 'oc get user "~"')
    ok("oc get user '~'", 'oc get user/~')
    ok('oc get users "~"', 'oc get user/~')
    ok('oc get user/~ -o yaml', 'oc get users/~ -o yaml')
    no('ls ~', "ls '~'")
    no('ls ~/notes', "ls '~/notes'")
    no('ls ~/notes/', 'ls ~/notes') // `ls file/` fails when it is a file: only cd, mkdir and rmdir take directories only
    ok('cd ~/notes/', 'cd ~/notes')
    no('ls ~learner', "ls '~learner'")
    no('cmd dir=~', "cmd dir='~'") // a word that looks like an assignment: bash expands `~` after `=`
    no('cmd dir=/a:~/b', "cmd dir='/a:~/b'")
    ok("sort --output=~ list", "sort --output='~' list") // `--output` is not a variable name: no expansion
    // other expansions are not modelled: only the exact accepted form passes
    no('oc get pods {web,db}', 'oc get pods web db')
    no('ls {a..c}', 'ls a b c')
    no('oc get pods !web', 'oc get pods web')
    no('oc get pods # every pod', 'oc get pods')
    no('oc get pods $NS', 'oc get pods')
    ok('./summarise.sh logs/{app,old}.log', './summarise.sh logs/{app,old}.log') // exact
  })
  it('parses oc and kubectl as the client does', () => {
    no('oc get pods --namespce x', 'oc get pods -n x') // unknown option: the client refuses the line
    no('oc get pods -n', 'oc get pods -n x') // flag needs an argument
    no('oc get secret htpass-secret -N openshift-config', 'oc get secret htpass-secret -n openshift-config')
    ok('oc get secret -n openshift-config htpass-secret', 'oc get secret htpass-secret -n openshift-config')
    ok('oc -o yaml get route ledger', 'oc get route ledger -o yaml') // cobra reads a value-taking option before the command
    no('oc --no-headers get pods', 'oc get pods --no-headers') // …but not a flag: "flags cannot be placed before plugin name"
    no('oc get pods -l a=b -l c=d', 'oc get pods -l c=d') // given twice: pflag keeps the last value but validates each one (exact match only)
    no('oc get pods -l a=b -l c=d', 'oc get pods -l a=b')
    ok('oc get pods --show-labels=true', 'oc get pods --show-labels')
    no('oc get pods --show-labels=false', 'oc get pods') // an explicit value is kept: unset can differ (skopeo --tls-verify)
    ok('oc get pods --show-labels=true', 'oc get pods --show-labels')
    no('oc get pods --show-labels=maybe', 'oc get pods --show-labels')
    ok('oc create cm settings --from-literal=a=1', 'oc create configmap settings --from-literal=a=1') // command alias
    ok('oc process -p B=2 -p A=1 shop', 'oc process shop -p A=1 -p B=2') // a repeatable option: order-free
    ok('oc get endpointslices -lkubernetes.io/service-name=web', 'oc get endpointslices -l kubernetes.io/service-name=web')
    ok('oc create deployment web --image=nginx --dry-run', 'oc create deployment web --dry-run --image=nginx') // optional value
    no('oc adm policy add-role-to-user view alice -n x', 'oc adm policy add-role-to-user alice view -n x')
    no('oc policy add-role-to-user view alice', 'oc adm policy add-role-to-user view alice')
    // resource names resolve as the client resolves them (found by the grading oracle: `ip` is IPAddress since 1.33)
    no('oc get ip install-7x9ab -n ops', 'oc get installplan install-7x9ab -n ops')
    ok('oc get ip x', 'oc get ipaddress x')
    ok('oc get installplans.operators.coreos.com x -n ops', 'oc get installplan x -n ops')
    no('curl --max-time=1 http://ledger:8080/', 'curl --max-time 1 http://ledger:8080/') // curl refuses `--max-time=1`
    ok('podman build . --tag=localhost/site:2.0', 'podman build . --tag localhost/site:2.0')
  })

  it('rejects the wrong commands found by the verification of the foundations lessons and by an independent review', () => {
    // each pair was shown wrong by running the real program
    no('ls -l --all=.', 'ls -l --all .') // --all takes no value
    no('ls --all=. -l', 'ls --all . -l')
    no('cat --number=notes/todo.txt', 'cat --number notes/todo.txt')
    no("grep --count=' 500 ' access.log", "grep --count ' 500 ' access.log")
    no('systemctl --user=stop academy-demo', 'systemctl --user stop academy-demo')
    no('tar --list=--verbose --file site.tar.xz', 'tar --list --verbose --file site.tar.xz')
    no('skopeo inspect --raw=docker://registry.access.redhat.com/ubi9/ubi-minimal:latest', 'skopeo inspect --raw docker://registry.access.redhat.com/ubi9/ubi-minimal:latest')
    no('ls --color always /etc/hosts', 'ls --color=always /etc/hosts') // an optional value must be attached
    no('ls -l My\\  Report.txt', 'ls -l My\\ Report.txt') // backslash, then two blanks: two names
    no('ls -l My\\\tReport.txt', 'ls -l My\\ Report.txt')
    no('oc get pods -n openshift-etcd', 'oc get pods -n openshift-etcd') // a no-break space does not separate words
    no("find project -name *'.log'", "find project -name '*.log'") // the * is still a pattern
    no('find project -name *".log"', "find project -name '*.log'")
    no('ls logs/*.txt/', 'ls logs/*.txt')
    no('kubectl apply -f web.yaml/', 'kubectl apply -f web.yaml') // "not a directory"
    no('oc create secret generic htpass-secret --from-file=users.htpasswd/ -n openshift-config --dry-run=client', 'oc create secret generic htpass-secret --from-file=users.htpasswd -n openshift-config --dry-run=client')
    no('find project -type f/ -name "*.log"', 'find project -type f -name "*.log"')
    no('rpm -qf .//usr/bin/tar', 'rpm -qf /usr/bin/tar') // `.//x` is relative
    no('df -i .//', 'df -i /')
    no('podman logs ./talker', 'podman logs talker') // a container name, not a path
    no('podman ./ps', 'podman ps')
    no('skopeo ./inspect docker://registry.access.redhat.com/ubi9/ubi-minimal:latest', 'skopeo inspect docker://registry.access.redhat.com/ubi9/ubi-minimal:latest')
    no('grep -c ./INFO logs/app.log', 'grep -c INFO logs/app.log')
    no('htpasswd -B -b users.htpasswd ./carol example-carol-pw', 'htpasswd -B -b users.htpasswd carol example-carol-pw')
    no('helm ./template preview lab/chart -f prod.yaml --set replicas=3', 'helm template preview lab/chart -f prod.yaml --set replicas=3')
    no('journalctl --user-unit ./academy-crash --no-pager', 'journalctl --user-unit academy-crash --no-pager')
    no('ip -br addr show ./lo', 'ip -br addr show lo')
    no('nohup x.sh', 'nohup ./x.sh')
    no('find project -name "*.log" --', 'find project -name "*.log"') // find refuses a trailing --
    no('htpasswd -B -b users.htpasswd carol example-carol-pw --', 'htpasswd -B -b users.htpasswd carol example-carol-pw')
    no('oc scale statefulset/web --replicas=1.5 --replicas=1', 'oc scale statefulset/web --replicas=1') // the first value is rejected
    no('kubectl scale deployment web --replicas=three --replicas=3', 'kubectl scale deployment web --replicas=3')
    no('grep -e -n', 'grep -en') // -e takes the rest of the group as its pattern
    no('ps -e -o -f', 'ps -eof')
    no('ls -I -a -l /etc/hosts', 'ls -aIl /etc/hosts')
    no('uniq -f -c 1', 'uniq -c -f 1')
    no('curl --insecure --no-insecure --silent file:///dev/null', 'curl --no-insecure --insecure --silent file:///dev/null') // the later one wins
    no('ls ~""', 'ls ~') // empty quotes stop tilde expansion
    no("ls ~''/notes", 'ls ~/notes')
    no('podman run --rm false busybox', 'podman run --rm=false busybox') // --rm takes no separate value
    no('podman run --name second busybox:latest sleep 1000 -d', 'podman run -d --name second busybox:latest sleep 1000') // after the image, -d is the container's
    ok('podman run -d --name second busybox:latest sleep 1000', 'podman run --name second -d busybox:latest sleep 1000')
    ok('podman run --name=web -p 8080:80 nginx', 'podman run -p 8080:80 --name web nginx')
    ok("oc exec deploy/toolbox -- getent hosts 'kubernetes.default'", 'oc exec deploy/toolbox -- getent hosts kubernetes.default') // quotes removed
    ok('ls -la', 'ls -a -l')
    ok('ls -l notes/todo.txt', 'ls -l ./notes/todo.txt')
  })

  it('rejects the wrong commands found by the second independent review', () => {
    no('podman ps --version=false', 'podman ps') // --version belongs to the podman command itself
    no('skopeo inspect --version=false docker://registry.access.redhat.com/ubi9/ubi-minimal:latest', 'skopeo inspect docker://registry.access.redhat.com/ubi9/ubi-minimal:latest')
    no('skopeo inspect --tls-verify=false docker://registry.access.redhat.com/ubi9/ubi-minimal:latest', 'skopeo inspect docker://registry.access.redhat.com/ubi9/ubi-minimal:latest')
    no('helm template preview lab/chart --set a=2 --set a.b=1', 'helm template preview lab/chart --set a.b=1 --set a=2')
    no('helm template preview lab/chart --set b=3 --set a=1,b=2', 'helm template preview lab/chart --set a=1,b=2 --set b=3')
    no('tree -L -a 1', 'tree -a -L 1')
    no('ss -A -n tcp', 'ss -n -A tcp')
    no('ls -lf /etc/hosts', 'ls -fl /etc/hosts') // -f turns -l off when it comes last
    no('ps -e -o args -ww', 'ps -e -o args -w')
    no('head -n ./2 /etc/hosts', 'head -n 2 /etc/hosts')
    no('oc create secret generic x --from-file=./key=/etc/hosts --dry-run=client', 'oc create secret generic x --from-file=key=/etc/hosts --dry-run=client')
    no('ls -l ./-- "My Report.txt"', 'ls -l -- "My Report.txt"')
    no('cat ./- /etc/hosts', 'cat - /etc/hosts')
    no("ls /etc/'[h]'osts*", 'ls /etc/[h]osts*')
    no("printf '%s\\n' di''r=~", "printf '%s\\n' dir=~")
    no('ls -l "say \\"a  b\\""', 'ls -l "say \\"a b\\""')
    ok('oc process shop -p B=2 -p A=1', 'oc process shop -p A=1 -p B=2')
    ok('ls -lt', 'ls -tl')
    ok('ls -la', 'ls -al')
    ok('oc create secret generic x --from-file=key=./a.txt --dry-run=client', 'oc create secret generic x --from-file=key=a.txt --dry-run=client')
  })
})
