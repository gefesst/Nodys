"""Index every approved reference against captured UI evidence, without claiming parity."""
import argparse
import html
import json
from pathlib import Path
from PIL import Image, ImageChops

MAPPING = {
    "channels-voice":"44-channel-voice-present",
    "friends-menu":"43g-friends-menu","chat-menu":"43h-chat-menu",
    "idea-new-messages":"43d-chat-new-messages","idea-offline-draft":"43e-chat-offline-draft",
    "idea-reconnected":"43f-chat-reconnected",
    "settings-saved":"42f-channel-settings-saved","settings-leave":"42g-channel-leave-confirm",
    "chat-unread":"43-chat-unread","chat-search":"43b-chat-search","stress-long-text":"43c-chat-long-text",
    "channels-text-empty":"42-channel-text-empty","channels-text-error":"42b-channel-text-error",
    "channels-text-denied":"42c-channel-text-denied","channels-voice-denied":"42d-channel-voice-denied",
    "channels-voice-quality":"44d-channel-voice-quality",
    "call-connecting":"41-call-connecting","call-busy":"41b-call-busy",
    "call-timeout":"41c-call-timeout","call-error":"41d-call-error",
    'auth-login':'01-auth-login', 'auth-login-error':'03c-auth-login-error',
    'auth-login-loading':'03d-auth-login-loading', 'auth-register':'02-auth-register',
    'auth-register-error':'03-auth-register-error', 'auth-register-loading':'02b-auth-register-loading',
    'friends-empty':'04b-friends-empty','friends-loading':'04c-friends-loading',
    'friends-requests-empty':'06a-friends-requests-empty',
    'chat-empty':'09b-chat-empty','chat-loading':'09c-chat-loading','chat-error':'09d-chat-error',
    'friends-all':'04-friends-all', 'friends-online':'05-friends-online',
    'friends-requests':'31-friend-request', 'friends-add':'07-friends-add-search',
    'friends-mini':'08-mini-profile', 'friends-remove':'06d-friend-remove-confirm',
    'friends-search-empty':'06b-friends-search-empty', 'friends-error':'06c-friends-network-error',
    '01-chat':'43i-chat-read', 'chat-none':'08b-chat-none', 'chat-multiline':'10-chat-multiline',
    'channels-empty':'40-channels-empty','channels-loading':'40b-channels-loading','channels-error':'40c-channels-error',
    'channels-invites-empty':'40d-channel-invites-empty','channels-join-error':'40e-channel-join-error',
    'channels-list':'11a-channel-list', 'channels-invites':'33-channel-invite',
    'channels-text':'12-channel-text', 'channels-create':'15-channel-create',
    'channels-join':'16-channel-join', 'channels-voice-empty':'14-channel-voice',
    'idea-voice-reconnect':'29e-channel-voice-reconnecting',
    'idea-mic-check':'29f-microphone-level','idea-mic-silent':'29g-microphone-silent','idea-mic-permission':'29h-microphone-permission',
    'channels-voice-active':'44b-channel-voice-active','channels-voice-muted':'44c-channel-voice-muted',
    'settings-loading':'16b-channel-settings-loading','settings-error':'17a-channel-settings-error',
    'settings-info':'17-channel-settings', 'settings-roles':'18b-channel-permissions',
    'settings-members':'18c-channel-members-roles', 'settings-regenerate':'17b-channel-regenerate-confirm',
    'settings-delete':'17c-channel-delete-confirm', 'profile-main':'19-profile',
    'profile-logout':'20d-profile-logout','profile-avatar':'20e-profile-avatar','profile-error':'20f-profile-save-error',
    'profile-edit':'20-profile-edit', 'profile-password':'21-profile-password',
    'profile-saving':'20b-profile-saving','profile-saved':'20c-profile-saved',
    'general-settings':'22-settings', 'idea-quick-switch':'22c-quick-switch',
    'idea-quick-empty':'22d-quick-switch-empty','call-outgoing':'24-outgoing-call',
    'call-active':'25-active-call','call-incoming':'27-incoming-call',
    'call-ended':'26b-call-result', 'call-muted':'26-call-muted',
    'call-quality':'26a-call-quality','call-declined':'27b-call-declined',
    'idea-voice-dock':'25b-voice-dock','chat-send-error':'36-network-error-draft',
}


def find_capture(name, folders):
    """Return only a frame recorded by its successful run, never stale files."""
    for candidate in folders:
        run=candidate/'review.json'
        if not run.exists():
            continue
        metadata=json.loads(run.read_text())
        path=candidate/'sizes'/f'{name}-1440.png'
        if metadata.get('error') is None and name in metadata.get('screens',[]) and path.exists():
            return path
    return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references',type=Path,required=True)
    parser.add_argument('--captures',type=Path,required=True)
    parser.add_argument('--additional-captures',type=Path,action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    catalog=json.loads((args.references/'catalog.json').read_text())
    report=[];cards=[]
    for item in catalog:
        slug=item['slug'];name=MAPPING.get(slug)
        actual=None
        if name:
            actual=find_capture(name,[args.captures]+args.additional_captures)
        reference=args.references/f'{slug}.png'
        record={'slug':slug,'title':item['title'],'capture':None,'visual_acceptance':'unverified'}
        folder=args.output/slug;folder.mkdir(exist_ok=True)
        ref=Image.open(reference).convert('RGB')
        if ref.size==(1600,1040):ref=ref.crop((80,70,1520,970))
        ref.save(folder/'reference.png')
        figures=f'<figure><img src="{slug}/reference.png"><figcaption>Макет</figcaption></figure>'
        if actual and actual.exists():
            live=Image.open(actual).convert('RGB')
            if live.size==ref.size:
                record['capture']=str(actual.resolve())
                run=actual.parent.parent/'review.json'
                record['run_report']=str(run.resolve())
                if run.exists():
                    metadata=json.loads(run.read_text())
                    record['source_revision']=metadata.get('source_revision')
                    record['source_tree_sha256']=metadata.get('source_tree_sha256')
                    record['run_error']=metadata.get('error')
                live.save(folder/'actual.png')
                Image.blend(ref,live,.5).save(folder/'overlay.png')
                ImageChops.difference(ref,live).save(folder/'difference.png')
                for kind,label in [('actual','Приложение'),('overlay','Наложение 50%'),('difference','Разница')]:
                    figures+=f'<figure><img src="{slug}/{kind}.png"><figcaption>{label}</figcaption></figure>'
        status='Снимок есть; совпадение ещё требует проверки' if record['capture'] else 'Нет сопоставленного снимка'
        report.append(record)
        cards.append(f'<section><h2>{html.escape(item["title"])} · {slug}</h2><p>{status}</p><div>{figures}</div></section>')
    (args.output/'coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    intro='<h1>Сверка полного каталога noda</h1><p>Это индекс доказательств, а не подтверждение готовности. Данные, состояние, время, системная рамка, фон и растеризация шрифтов могут различаться. Пустые строки нельзя считать проверенными.</p>'
    style='<style>body{background:#18212a;color:#edf2fa;font:14px Arial;margin:24px}section{margin:36px 0}section div{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}img{width:100%}figcaption{padding:8px}h2{font-size:20px}</style>'
    (args.output/'index.html').write_text('<!doctype html><meta charset="utf-8">'+style+intro+''.join(cards))
    print(json.dumps({'references':len(report),'mapped_captures':sum(bool(r['capture']) for r in report),'accepted':0}))

if __name__=='__main__':main()
