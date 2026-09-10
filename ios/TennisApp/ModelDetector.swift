import Foundation
import CoreML
import CoreImage
import CoreVideo
import TennisCore

struct ModelManifest: Decodable {
    struct Input: Decodable { var name:String; var width:Int; var height:Int; var resize:String; var paddingValue:Double }
    struct Output: Decodable { var name:String; var shape:[Int]; var layout:String; var coordinates:String; var nms:Bool }
    var schemaVersion:Int; var modelId:String; var packageSha256:String; var input:Input; var output:Output
    var classes:[String:String]; var confidenceThreshold:Double
}
struct DetectedObjects { var balls:[Detection]=[]; var players:[Detection]=[]; var rackets:[Detection]=[] }

/// Uses the exported tensor contract, never assumes Vision recognized-object output.
/// YOLO26 end-to-end exports [1,N,6] and does not require a second NMS pass.
final class ModelDetector {
    let manifest:ModelManifest
    private let model:MLModel
    private let context=CIContext(options:[.cacheIntermediates:false])
    init() throws {
        guard let manifestURL=(Bundle.main.url(forResource:"ModelManifest",withExtension:"json",subdirectory:"Models") ?? Bundle.main.url(forResource:"ModelManifest",withExtension:"json")),
              let modelURL=Bundle.main.url(forResource:"Detector",withExtension:"mlmodelc") ?? Bundle.main.url(forResource:"Detector",withExtension:"mlmodelc",subdirectory:"Models") else {
            throw PackageError.invalid(String(localized:"model.missing"))
        }
        manifest=try ContractJSON.read(ModelManifest.self,from:manifestURL)
        guard manifest.schemaVersion==1,manifest.input.resize=="letterbox",manifest.input.width>0,manifest.input.height>0,
              manifest.output.layout=="xyxy_confidence_class",manifest.output.coordinates=="input_pixels_top_left",!manifest.output.nms else {
            throw PackageError.invalid(String(localized:"model.incompatible"))
        }
        let config=MLModelConfiguration(); config.computeUnits = .all
        model=try MLModel(contentsOf:modelURL,configuration:config)
        guard model.modelDescription.inputDescriptionsByName[manifest.input.name] != nil,
              model.modelDescription.outputDescriptionsByName[manifest.output.name] != nil else { throw PackageError.invalid(String(localized:"model.incompatible")) }
    }
    var provenance:[String:String] { ["detector":manifest.packageSha256,"model_id":manifest.modelId,"runtime":"tennis-ios-2.0.0"] }
    func predict(image:CIImage,width:Int,height:Int)throws->DetectedObjects {
        let iw=manifest.input.width,ih=manifest.input.height
        let scale=min(Double(iw)/Double(width),Double(ih)/Double(height))
        let rw=Int((Double(width)*scale).rounded()),rh=Int((Double(height)*scale).rounded())
        let left=(iw-rw)/2,top=(ih-rh)/2,bottom=ih-rh-top
        var pixel:CVPixelBuffer?
        let attributes:[CFString:Any]=[kCVPixelBufferCGImageCompatibilityKey:true,kCVPixelBufferCGBitmapContextCompatibilityKey:true,kCVPixelBufferIOSurfacePropertiesKey:[:]]
        guard CVPixelBufferCreate(kCFAllocatorDefault,iw,ih,kCVPixelFormatType_32BGRA,attributes as CFDictionary,&pixel)==kCVReturnSuccess,let pixel else { throw PackageError.invalid("Cannot allocate model input") }
        let extent=image.extent
        let normalized=image.transformed(by:CGAffineTransform(translationX:-extent.minX,y:-extent.minY))
        let resized=normalized.transformed(by:CGAffineTransform(scaleX:Double(rw)/extent.width,y:Double(rh)/extent.height)).transformed(by:CGAffineTransform(translationX:Double(left),y:Double(bottom)))
        let padding=manifest.input.paddingValue/255
        let background=CIImage(color:CIColor(red:padding,green:padding,blue:padding)).cropped(to:CGRect(x:0,y:0,width:iw,height:ih))
        context.render(resized.composited(over:background),to:pixel,bounds:CGRect(x:0,y:0,width:iw,height:ih),colorSpace:CGColorSpace(name:CGColorSpace.sRGB))
        let provider=try MLDictionaryFeatureProvider(dictionary:[manifest.input.name:MLFeatureValue(pixelBuffer:pixel)])
        let prediction=try model.prediction(from:provider)
        guard let output=prediction.featureValue(for:manifest.output.name)?.multiArrayValue,
              output.shape.count==3,output.shape[0].intValue==1,output.shape[2].intValue==6 else { throw PackageError.invalid(String(localized:"model.incompatible")) }
        var detections=DetectedObjects()
        for row in 0..<output.shape[1].intValue {
            let values=(0..<6).map { output[[0,NSNumber(value:row),NSNumber(value:$0)]].doubleValue }
            guard values.allSatisfy(\.isFinite),values[4]>=manifest.confidenceThreshold else { continue }
            let key=String(Int(values[5].rounded())),name=manifest.classes[key]?.lowercased() ?? ""
            let box=[max(0,min(Double(width),(values[0]-Double(left))*Double(width)/Double(rw))),
                     max(0,min(Double(height),(values[1]-Double(top))*Double(height)/Double(rh))),
                     max(0,min(Double(width),(values[2]-Double(left))*Double(width)/Double(rw))),
                     max(0,min(Double(height),(values[3]-Double(top))*Double(height)/Double(rh)))]
            guard box[2]>box[0],box[3]>box[1] else { continue }
            let d=Detection(box:box,confidence:values[4])
            if ["sports ball","tennis ball","ball"].contains(name) { detections.balls.append(d) }
            else if name=="person" { detections.players.append(d) }
            else if ["tennis racket","racket"].contains(name) { detections.rackets.append(d) }
        }
        return detections
    }
}
